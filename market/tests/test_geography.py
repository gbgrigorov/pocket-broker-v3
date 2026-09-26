import datetime as dt
import io
from decimal import Decimal

from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from crm.dedup import find_possible_duplicates
from market.geography_seed_v1 import seed
from market.models import City, Neighbourhood, NeighbourhoodAlias, OfferGeo
from sourcing.models import Agency, Offer, OfferHistory
from sourcing.web.store import store


class GeographyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed(apps)
        cls.agency = Agency.objects.create(slug='test-agency', name='Agency')
        cls.sofia = City.objects.get(slug='sofia')
        cls.varna = City.objects.get(slug='varna')

    def offer(self, location='', **kwargs):
        key = str(Offer.objects.count() + 1)
        values = dict(agency=self.agency, fingerprint=key, listing_url=f'https://agency.example/{key}',
                      first_seen=dt.date(2026, 9, 25), last_seen=dt.date(2026, 9, 25), location=location)
        values.update(kwargs)
        return Offer.objects.create(**values)

    def ids(self, **params):
        response = self.client.get('/api/offers/', params)
        self.assertEqual(response.status_code, 200)
        return {o['id'] for o in response.json()['results']}

    def test_cities_resolve_independently_of_legacy_setting(self):
        with self.settings(MARKET_CITY='София'):
            varna = self.offer('Варна, Левски')
            sofia = self.offer('София, Левски')
        self.assertEqual(varna.geo.city, self.varna)
        self.assertEqual(sofia.geo.city, self.sofia)
        self.assertNotEqual(varna.geo.neighbourhood_id, sofia.geo.neighbourhood_id)

    def test_alias_punctuation_cyrillic_latin_abbreviations_and_number_boundaries(self):
        for text, slug in [('гр. София, ж.к. Младост-1А', 'mladost-1a'),
                           ('Sofia Mladost 1A', 'mladost-1a'),
                           ('София кв. Лозенец', 'lozenets'),
                           ('Sofia Lozenec', 'lozenets'),
                           ('София, Студ. град', 'studentski-grad'),
                           ('София ж.к. Люлин-10', 'lyulin-10'),
                           ('Sofia zona B18', 'zona-b-18')]:
            with self.subTest(text=text):
                self.assertEqual(self.offer(text).geo.neighbourhood.slug, slug)

    def test_unknown_neighbourhood_is_ingestible_with_source_city(self):
        row = self.offer('Непознат квартал', evidence={'city': 'sofia'})
        self.assertEqual(row.geo.city, self.sofia)
        self.assertIsNone(row.geo.neighbourhood)
        self.assertEqual(row.geo.raw_location, 'Непознат квартал')
        self.assertLess(row.geo.confidence, Decimal('0.5'))

    def test_source_context_cannot_override_explicit_city(self):
        row = self.offer('Варна, Център', evidence={'city': 'sofia'})
        self.assertEqual(row.geo.city, self.varna)

    def test_region_or_crawl_context_cannot_relabel_another_town(self):
        for location in ['Бяла', 'Каварна', 'Пловдив', 'гр. Пловдив, Център']:
            row = self.offer(location, location_raw=f'{location}, област Варна', evidence={'city': 'sofia'})
            self.assertIsNone(row.geo.city)

    def test_newly_curated_city_can_resolve_without_a_new_offer_model(self):
        city = City.objects.create(country=self.varna.country, slug='byala', name_bg='Бяла', name_en='Byala')
        self.assertEqual(self.offer('Бяла').geo.city, city)

    def test_country_name_is_not_a_neighbourhood_without_a_quarter_label(self):
        row = self.offer('Sofia', location_raw='Bulgaria, Sofia, Lozenets')
        self.assertEqual(row.geo.neighbourhood.slug, 'lozenets')
        self.assertIsNone(self.offer('Bulgaria, Sofia').geo.neighbourhood)
        self.assertEqual(self.offer('София, кв. България').geo.neighbourhood.slug, 'bulgaria')

    def test_city_substring_and_shared_quarter_cannot_guess_city(self):
        for location in ['Каварна', 'Левски', 'София Варна', '']:
            with self.subTest(location=location):
                self.assertIsNone(self.offer(location).geo.city)

    def test_blank_legacy_live_catalogue_retains_known_varna_context(self):
        self.assertEqual(self.offer('', evidence={'crawler': 'crawl_live'}).geo.city, self.varna)

    def test_ambiguous_alias_does_not_force_match(self):
        iztok = Neighbourhood.objects.get(city=self.sofia, slug='iztok')
        NeighbourhoodAlias.objects.create(neighbourhood=iztok, alias='Lozenets')
        row = self.offer('Sofia Lozenets')
        self.assertEqual(row.geo.city, self.sofia)
        self.assertIsNone(row.geo.neighbourhood)

    def test_city_and_neighbourhood_pair_validation(self):
        geo = self.offer('София Лозенец').geo
        geo.city = self.varna
        with self.assertRaises(ValidationError):
            geo.save()

    def test_database_geography_constraints(self):
        row = self.offer('София Лозенец')
        with self.assertRaises(IntegrityError), transaction.atomic():
            OfferGeo.objects.create(offer=row)
        with self.assertRaises(IntegrityError), transaction.atomic():
            OfferGeo.objects.filter(offer=row).update(confidence=2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            OfferGeo.objects.filter(offer=row).update(city=None)

    def test_seed_is_idempotent_preserves_manual_curation_and_core_rows(self):
        row = self.offer('София Лозенец')
        row.geo.matched_by = 'manual'
        row.geo.neighbourhood = None
        row.geo.save()
        before = list(Offer.objects.values())
        counts = [City.objects.count(), Neighbourhood.objects.count(), NeighbourhoodAlias.objects.count()]
        for _ in range(2):
            call_command('seed_geography', resolve=True, stdout=io.StringIO())
        self.assertEqual(counts, [City.objects.count(), Neighbourhood.objects.count(), NeighbourhoodAlias.objects.count()])
        self.assertEqual(before, list(Offer.objects.values()))
        row.save()
        row.geo.refresh_from_db()
        self.assertEqual(row.geo.matched_by, 'manual')
        self.assertIsNone(row.geo.neighbourhood)

    def test_bulk_ingest_can_be_backfilled(self):
        row = self.offer('София Лозенец')
        row.geo.delete()
        call_command('seed_geography', stdout=io.StringIO())
        self.assertEqual(OfferGeo.objects.get(offer=row).city, self.sofia)

    def test_web_identity_price_history_and_geography_survive_price_change(self):
        record = {'listing_url': 'https://agency.example/42', 'location': 'София, Лозенец', 'price_eur': 250000}
        self.assertEqual(store(self.agency, record, {'city': 'sofia'}), 'new')
        row = Offer.objects.get(listing_url=record['listing_url'])
        original_id, original_key = row.pk, row.fingerprint
        record['price_eur'] = 240000
        self.assertEqual(store(self.agency, record, {'city': 'sofia'}), 'changed')
        row.refresh_from_db()
        self.assertEqual((row.pk, row.fingerprint), (original_id, original_key))
        self.assertEqual(Offer.objects.count(), 1)
        self.assertEqual(row.history.filter(field='price_eur').count(), 1)
        self.assertEqual(row.geo.city, self.sofia)

    def test_city_filter_and_unscoped_api_preserve_inventory(self):
        v = self.offer('Варна')
        s = self.offer('София')
        u = self.offer('Каварна')
        self.assertEqual(self.ids(city='varna'), {v.pk})
        self.assertEqual(self.ids(city='sofia'), {s.pk})
        self.assertEqual(self.ids(), {v.pk, s.pk, u.pk})
        self.assertEqual(self.ids(city='bad-city'), set())

    def test_neighbourhood_filter_keeps_only_matching_or_unknown_in_city(self):
        v = self.offer('Варна Левски')
        s = self.offer('София Левски')
        self.offer('София Лозенец')
        unknown = self.offer('София')
        self.assertEqual(self.ids(city='sofia', neighbourhood='levski'), {s.pk, unknown.pk})
        self.assertEqual(self.ids(city='varna', neighbourhood='levski'), {v.pk})
        self.assertEqual(self.ids(neighbourhood='levski'), set())
        self.assertEqual(self.ids(city='sofia', neighbourhood='nonexistent'), set())

    def test_unknown_numeric_fields_stay_eligible(self):
        row = self.offer('София', price_eur=None, area_m2=None, bedrooms=None)
        self.offer('София', price_eur=500000)
        self.offer('Варна')
        self.assertEqual(self.ids(city='sofia', price_max='250000', area_min='80', beds='2'), {row.pk})

    def test_counts_facets_and_agencies_use_city_scope(self):
        self.offer('Варна')
        self.offer('Варна', deal_type='rent')
        other = Agency.objects.create(slug='sofia-only', name='Other')
        self.offer('София', agency=other)
        stats = self.client.get('/api/stats/', {'city': 'sofia'}).json()
        self.assertEqual((stats['offers'], stats['agencies'], stats['rent']), (1, 1, 0))
        facets = self.client.get('/api/facets/', {'city': 'sofia'}).json()
        self.assertEqual(facets['total'], 1)
        self.assertEqual(facets['deals'], [{'key': 'sale', 'count': 1}, {'key': 'rent', 'count': 0}])
        agencies = self.client.get('/api/agencies/', {'city': 'sofia'}).json()['agencies']
        self.assertEqual([a['slug'] for a in agencies], ['sofia-only'])

    def test_sibling_keys_isolate_cities_deals_and_unresolved_offers(self):
        v = self.offer('Варна', dedup_key='shared')
        s = self.offer('София', dedup_key='shared')
        sibling = self.offer('София', dedup_key='shared')
        self.offer('София', dedup_key='shared', deal_type='rent')
        unknown = self.offer('', dedup_key='shared')
        result = self.client.get(f'/api/offers/{s.pk}/').json()
        self.assertEqual([r['id'] for r in result['siblings']], [sibling.pk])
        self.assertEqual(result['cluster_key'], 'sofia:sale:shared')
        self.assertEqual(self.client.get(f'/api/offers/{unknown.pk}/').json()['siblings'], [])
        self.assertEqual(self.client.get(f'/api/offers/{v.pk}/', {'city': 'sofia'}).status_code, 404)

    def test_fuzzy_sql_cannot_join_shared_neighbourhood_across_cities(self):
        reference = self.offer('Левски', evidence={'city': 'sofia'}, title_norm='unique building')
        other = Agency.objects.create(slug='another', name='Another')
        same = self.offer('Левски', evidence={'city': 'sofia'}, title_norm='unique building', agency=other)
        self.offer('Левски', evidence={'city': 'varna'}, title_norm='unique building', agency=other)
        self.offer('Левски', title_norm='unique building', agency=other)
        self.assertEqual([o['id'] for o in find_possible_duplicates(reference)], [same.pk])

    def test_geography_endpoints_and_empty_sofia(self):
        self.offer('Варна')
        self.offer('София', is_active=False)
        self.assertEqual(self.ids(city='sofia'), set())
        self.assertEqual({c['slug'] for c in self.client.get('/api/cities/').json()['cities']}, {'varna', 'sofia'})
        self.assertEqual(self.client.get('/api/neighbourhoods/').status_code, 400)
        rows = self.client.get('/api/neighbourhoods/', {'city': 'sofia'}).json()['neighbourhoods']
        self.assertIn('lozenets', {r['slug'] for r in rows})
        self.assertEqual(self.client.post('/api/cities/').status_code, 405)


class GeographyMigrationTests(TransactionTestCase):
    def test_existing_rows_backfill_without_changing_supply_or_lifecycle(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        executor.migrate([('market', '0004_alter_siteprobe_options_siteprobe_run_id_and_more')])
        old = executor.loader.project_state([
            ('market', '0004_alter_siteprobe_options_siteprobe_run_id_and_more'),
            ('sourcing', '0001_initial'),
        ]).apps
        try:
            AgencyOld = old.get_model('sourcing', 'Agency')
            OfferOld = old.get_model('sourcing', 'Offer')
            HistoryOld = old.get_model('sourcing', 'OfferHistory')
            agency = AgencyOld.objects.create(slug='migration-agency', name='Migration')
            for key, location, active in [('v', 'Варна Левски', True), ('s', 'София Левски', False), ('u', 'Каварна', True)]:
                row = OfferOld.objects.create(agency=agency, fingerprint=key, location=location,
                    first_seen=dt.date(2026, 1, 1), last_seen=dt.date(2026, 9, 1), is_active=active,
                    evidence={'source_url': 'https://agency.example/1'})
                HistoryOld.objects.create(offer=row, event='changed', field='price_eur',
                    old_value='250000', new_value='240000', changed_on=dt.date(2026, 9, 1))
            before = list(OfferOld.objects.order_by('pk').values())
            histories = list(HistoryOld.objects.order_by('pk').values())
            executor = MigrationExecutor(connection)
            executor.migrate([('market', '0006_seed_geography_backfill')])
            self.assertEqual(before, list(Offer.objects.order_by('pk').values()))
            self.assertEqual(histories, list(OfferHistory.objects.order_by('pk').values()))
            self.assertEqual(OfferGeo.objects.count(), 3)
            self.assertEqual(OfferGeo.objects.get(offer__fingerprint='v').city.slug, 'varna')
            self.assertEqual(OfferGeo.objects.get(offer__fingerprint='s').city.slug, 'sofia')
            self.assertIsNone(OfferGeo.objects.get(offer__fingerprint='u').city)
        finally:
            MigrationExecutor(connection).migrate(latest)
