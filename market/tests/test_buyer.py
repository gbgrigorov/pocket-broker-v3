import datetime as dt
import json

from django.apps import apps
from django.test import Client, TestCase

from market.geography_seed_v1 import seed
from sourcing.models import Agency, Offer


class BuyerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed(apps)
        cls.agency = Agency.objects.create(slug='buyer-test', name='Buyer test')

    def offer(self, **kwargs):
        number = Offer.objects.count() + 1
        defaults = dict(agency=self.agency, fingerprint=f'buyer-{number}',
                        listing_url=f'https://agency.example/{number}',
                        first_seen=dt.date(2026, 9, 25), last_seen=dt.date(2026, 9, 25),
                        location='София, Лозенец', property_kind='двустаен',
                        bedrooms=1, price_eur=150000, area_m2=65, deal_type='sale')
        defaults.update(kwargs)
        return Offer.objects.create(**defaults)

    def profile(self, **kwargs):
        return dict({'city': 'sofia', 'deal': 'sale', 'kind': 'apartment', 'rooms': 2,
                     'price_min': 100000, 'price_max': 200000,
                     'neighbourhoods': ['lozenets'], 'features': [], 'pets': 'none'}, **kwargs)

    def matches(self, profile=None, **kwargs):
        return self.client.post('/api/buyer/matches/',
                                data=json.dumps({'profile': profile or self.profile(), **kwargs}),
                                content_type='application/json')

    def test_two_rooms_means_one_bedroom_and_scopes_city_deal_and_inventory(self):
        wanted = self.offer()
        self.offer(property_kind='тристаен', bedrooms=2)
        self.offer(location='Варна, Левски')
        self.offer(deal_type='rent')
        self.offer(is_active=False)
        self.offer(property_kind='гараж', bedrooms=None)
        self.offer(listing_url='')
        rows = self.matches().json()['results']
        self.assertEqual([row['id'] for row in rows], [wanted.pk])
        self.assertIn('2 стаи', rows[0]['match']['reasons'])

    def test_room_kind_and_bedroom_fallback(self):
        wanted = self.offer(property_kind='apartment', bedrooms=1)
        four = self.offer(property_kind='четиристаен', bedrooms=3)
        self.assertEqual([row['id'] for row in self.matches().json()['results']], [wanted.pk])
        result = self.matches(self.profile(rooms=4)).json()['results']
        self.assertEqual([row['id'] for row in result], [four.pk])
        self.assertEqual(result[0]['match']['band'], 'verified')

    def test_full_catalogue_commercial_types_do_not_match_apartment_profiles(self):
        wanted = self.offer()
        for kind in ['Търговски имот', 'Други бизнес имоти', 'Ресторант, Бар',
                     'Производствена база', 'Regulated plot', 'Warehouse', 'Жилищна сграда']:
            self.offer(property_kind=kind, bedrooms=None)
        self.assertEqual([r['id'] for r in self.matches().json()['results']], [wanted.pk])

    def test_catalogue_offers_after_page_sixty_are_accessible(self):
        from unittest.mock import patch
        oldest = self.offer()
        for _ in range(60):
            self.offer()
        with patch('market.api.PER_PAGE', 1):
            result = self.client.get('/api/offers/', {'city': 'sofia', 'page': 61}).json()
            self.assertEqual(result['page'], 61)
            self.assertEqual([r['id'] for r in result['results']], [oldest.pk])

    def test_budget_area_and_multiple_neighbourhoods_are_requirements(self):
        lozenets = self.offer()
        iztok = self.offer(location='София, Изток')
        self.offer(location='София, Младост 1')
        self.offer(price_eur=210000)
        self.offer(price_eur=90000)
        self.offer(area_m2=40)
        result = self.matches(self.profile(neighbourhoods=['lozenets', 'iztok'], area_min=60)).json()
        self.assertEqual({row['id'] for row in result['results']}, {lozenets.pk, iztok.pk})

    def test_missing_facts_remain_eligible_and_rank_below_confirmed_matches(self):
        known = self.offer()
        unknown = self.offer(location='София', price_eur=None, bedrooms=None, property_kind='', area_m2=None)
        result = self.matches(self.profile(area_min=60)).json()['results']
        self.assertEqual([row['id'] for row in result], [known.pk, unknown.pk])
        self.assertEqual(result[0]['match']['confidence'], 100)
        self.assertEqual(result[0]['match']['band'], 'verified')
        self.assertEqual(result[1]['match']['band'], 'unverified')
        self.assertIn('Бюджет', result[1]['match']['unknown'])
        self.assertIn('Квартал', result[1]['match']['unknown'])

    def test_features_distinguish_yes_no_and_unknown(self):
        yes = self.offer(notes='С асансьор', furnished=True)
        unknown = self.offer(furnished=None)
        self.offer(notes='Без асансьор', furnished=True)
        self.offer(notes='С асансьор', furnished=False)
        rows = self.matches(self.profile(features=['lift', 'furnished'])).json()['results']
        self.assertEqual([row['id'] for row in rows], [yes.pk, unknown.pk])
        self.assertEqual(rows[0]['match']['confidence'], 100)
        self.assertIn('Асансьор', rows[1]['match']['unknown'])

    def test_pet_restrictions_only_apply_to_rentals_with_pets(self):
        no = self.offer(notes='No pets', deal_type='rent', price_eur=700)
        yes = self.offer(notes='Pets allowed', deal_type='rent', price_eur=700)
        unknown = self.offer(deal_type='rent', price_eur=700)
        profile = self.profile(deal='rent', price_min=500, price_max=900, pets='dog')
        rows = self.matches(profile).json()['results']
        self.assertEqual([row['id'] for row in rows], [yes.pk, unknown.pk])
        self.assertIn('Домашни любимци са разрешени', rows[1]['match']['unknown'])
        rows = self.matches(dict(profile, pets='none')).json()['results']
        self.assertEqual({row['id'] for row in rows}, {yes.pk, unknown.pk, no.pk})
        sale = self.offer(notes='No pets')
        self.assertIn(sale.pk, {row['id'] for row in self.matches(self.profile(pets='cat')).json()['results']})

    def test_negated_features_and_future_act16_are_never_confirmed(self):
        for token, negative, positive in [('garden', 'Без двор', 'С двор'),
                                          ('parking', 'Без паркомясто', 'С паркомясто'),
                                          ('act16', 'Пред Акт 16', 'Акт 16')]:
            with self.subTest(token=token):
                Offer.objects.all().delete()
                self.offer(notes=negative)
                wanted = self.offer(notes=positive)
                rows = self.matches(self.profile(features=[token])).json()['results']
                self.assertEqual([row['id'] for row in rows], [wanted.pk])
        for phrase in ['Акт 16 се очаква през 2027', 'Акт 16 през 2027', 'Предстои акт 16']:
            self.offer(notes=phrase)
        self.assertEqual(self.matches(self.profile(features=['act16'])).json()['total'], 1)

    def test_invalid_criteria_fail_without_broadening_results(self):
        self.offer()
        invalid = [dict(city='nonexistent'), dict(neighbourhoods=['nonexistent']),
                   dict(neighbourhoods=['chaika']), dict(price_min=200001, price_max=200000),
                   dict(price_max='1e6'), dict(price_max=True), dict(price_max=-1),
                   dict(rooms=0), dict(rooms=11), dict(rooms=[]), dict(features=['invented']),
                   dict(features='lift'), dict(deal='other'), dict(kind='land'), dict(pets='invalid')]
        for values in invalid:
            with self.subTest(values=values):
                self.assertEqual(self.matches(self.profile(**values)).status_code, 400)
        self.assertEqual(self.matches(page=0).status_code, 400)
        self.assertEqual(self.matches(page=True).status_code, 400)
        for payload in ['broken', '[]', '{"profile": null}']:
            self.assertEqual(self.client.post('/api/buyer/matches/', data=payload,
                                             content_type='application/json').status_code, 400)

    def test_pagination_and_no_mutation_of_supply_or_session(self):
        for _ in range(26):
            self.offer()
        before = list(Offer.objects.order_by('pk').values())
        first = self.matches().json()
        second = self.matches(page=2).json()
        self.assertEqual((first['total'], len(first['results']), len(second['results'])), (26, 24, 2))
        self.assertTrue({row['id'] for row in first['results']}.isdisjoint({row['id'] for row in second['results']}))
        self.assertEqual(before, list(Offer.objects.order_by('pk').values()))
        self.assertNotIn('sessionid', self.client.cookies)

    def test_wishlist_returns_current_data_and_preserves_unavailable_ids(self):
        active = self.offer()
        inactive = self.offer(is_active=False)
        missing = inactive.pk + 10000
        result = self.client.post('/api/buyer/wishlist/', data=json.dumps({'ids': [active.pk, inactive.pk, missing]}),
                                  content_type='application/json').json()
        self.assertEqual([row['id'] for row in result['results']], [active.pk])
        self.assertEqual(result['unavailable'], [inactive.pk, missing])
        Offer.objects.filter(pk=active.pk).update(price_eur=145000)
        result = self.client.post('/api/buyer/wishlist/', data=json.dumps({'ids': [active.pk, active.pk]}),
                                  content_type='application/json').json()
        self.assertEqual(len(result['results']), 1)
        self.assertEqual(result['results'][0]['price'], 145000)
        for ids in [[True], [-1], ['1'], [2**64], list(range(1, 202)), None]:
            self.assertEqual(self.client.post('/api/buyer/wishlist/', data=json.dumps({'ids': ids}),
                                             content_type='application/json').status_code, 400)

    def test_csrf_protection_and_read_only_methods(self):
        client = Client(enforce_csrf_checks=True)
        payload = json.dumps({'profile': self.profile()})
        self.assertEqual(client.post('/api/buyer/matches/', data=payload, content_type='application/json').status_code, 403)
        options = client.get('/api/buyer/options/')
        self.assertIn('no-store', options.headers['Cache-Control'])
        self.assertEqual(client.post('/api/buyer/matches/', data=payload, content_type='application/json',
                                    HTTP_X_CSRFTOKEN=options.json()['csrf_token']).status_code, 200)
        self.assertEqual(client.get('/api/buyer/matches/').status_code, 405)
        self.assertEqual(client.get('/api/buyer/wishlist/').status_code, 405)
        self.assertEqual(client.post('/api/buyer/options/', HTTP_X_CSRFTOKEN=options.json()['csrf_token']).status_code, 405)
