"""Frozen seed/backfill rules shared with migration 0006. Do not change v1 rules.

Future seed changes need a new version so historical migrations stay repeatable.
No network calls, current-model imports, or destructive supply writes.
"""
import re
import unicodedata

_TRANSLIT = dict(zip('абвгдежзийклмнопрстуфхцчшщъьюя',
                    ['a','b','v','g','d','e','zh','z','i','y','k','l','m','n','o',
                     'p','r','s','t','u','f','h','ts','ch','sh','sht','a','y','yu','ya']))

# Known non-target cities/settlements. A Varna region label in location_raw
# must not relabel an explicitly named coastal town as Varna city.
OUTSIDE = {'kavarna', 'byala', 'obzor', 'burgas', 'plovdiv', 'ruse', 'balchik',
           'slanchev bryag', 'sunny beach', 'albena', 'nesebar', 'sozopol',
           'pomorie', 'bansko', 'sveti vlas'}


def normalize(value):
    value = unicodedata.normalize('NFKC', value or '').casefold()
    value = ''.join(_TRANSLIT.get(c, c) for c in value)
    value = re.sub(r'[^a-z0-9]+', ' ', value)
    value = re.sub(r'(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])', ' ', value)
    return ' '.join(value.split())


# slug, Bulgarian name, English name, additional spelling variants.
SOFIA = [
    ('lozenets', 'Лозенец', 'Lozenets', 'Lozenec'),
    ('iztok', 'Изток', 'Iztok', ''),
    ('izgrev', 'Изгрев', 'Izgrev', ''),
    ('oborishte', 'Оборище', 'Oborishte', ''),
    ('geo-milev', 'Гео Милев', 'Geo Milev', ''),
    ('reduta', 'Редута', 'Reduta', ''),
    ('mladost-1a', 'Младост 1А', 'Mladost 1A', 'Младост-1А'),
    ('studentski-grad', 'Студентски град', 'Studentski Grad', 'Студ. град|Studentski'),
    ('vitosha', 'Витоша', 'Vitosha', ''),
    ('krastova-vada', 'Кръстова вада', 'Krastova Vada', 'Krystova Vada|Кр. вада'),
    ('hladilnika', 'Хладилника', 'Hladilnika', ''),
    ('manastirski-livadi', 'Манастирски ливади', 'Manastirski Livadi', 'Ман. ливади'),
    ('borovo', 'Борово', 'Borovo', ''),
    ('beli-brezi', 'Бели брези', 'Beli Brezi', ''),
    ('bulgaria', 'България', 'Bulgaria', 'Balgariya'),
    ('gotse-delchev', 'Гоце Делчев', 'Gotse Delchev', 'Goce Delchev'),
    ('strelbishte', 'Стрелбище', 'Strelbishte', ''),
    ('hipodruma', 'Хиподрума', 'Hipodruma', ''),
    ('ivan-vazov', 'Иван Вазов', 'Ivan Vazov', ''),
    ('center', 'Център', 'Center', 'Централен|Център София|Centre|Tsentar|Centar'),
    ('zona-b-5', 'Зона Б-5', 'Zona B-5', 'Зона Б5'),
    ('zona-b-18', 'Зона Б-18', 'Zona B-18', 'Зона Б18'),
    ('banishora', 'Банишора', 'Banishora', ''),
    ('hadji-dimitar', 'Хаджи Димитър', 'Hadji Dimitar', 'Hadzhi Dimitar|Х. Димитър'),
    ('poduyane', 'Подуяне', 'Poduyane', 'Poduene'),
    ('slatina', 'Слатина', 'Slatina', ''),
    ('nadezhda', 'Надежда', 'Nadezhda', ''),
    ('ovcha-kupel', 'Овча купел', 'Ovcha Kupel', ''),
    ('gorna-banya', 'Горна баня', 'Gorna Banya', ''),
    ('boyana', 'Бояна', 'Boyana', ''),
    ('dragalevtsi', 'Драгалевци', 'Dragalevtsi', 'Dragalevci'),
    ('simeonovo', 'Симеоново', 'Simeonovo', ''),
    ('malinova-dolina', 'Малинова долина', 'Malinova Dolina', ''),
    ('knyazhevo', 'Княжево', 'Knyazhevo', 'Kniazhevo'),
    ('pavlovo', 'Павлово', 'Pavlovo', ''),
    ('krasno-selo', 'Красно село', 'Krasno Selo', ''),
    ('sveta-troitsa', 'Света Троица', 'Sveta Troitsa', 'Св. Троица|Sveta Troica'),
    ('tolstoy', 'Толстой', 'Tolstoy', 'Tolstoi'),
    ('levski', 'Левски', 'Levski', ''),
    ('vrazhdebna', 'Враждебна', 'Vrazhdebna', ''),
] + [(f'mladost-{i}', f'Младост {i}', f'Mladost {i}', '') for i in range(1, 5)] + [
    (f'druzhba-{i}', f'Дружба {i}', f'Druzhba {i}', '') for i in range(1, 3)
] + [(f'lyulin-{i}', f'Люлин {i}', f'Lyulin {i}', f'Liulin {i}|Ljulin {i}') for i in range(1, 11)]

VARNA = [
    ('center', 'Център', 'Center', 'Centre|Centar'),
    ('levski', 'Левски', 'Levski', 'Базар Левски'),
    ('vinitsa', 'Виница', 'Vinitsa', 'Vinica'),
    ('asparuhovo', 'Аспарухово', 'Asparuhovo', ''),
    ('galata', 'Галата', 'Galata', ''),
    ('briz', 'Бриз', 'Briz', ''),
    ('chayka', 'Чайка', 'Chayka', 'Chaika'),
    ('troshevo', 'Трошево', 'Troshevo', ''),
    ('vladislav-varnenchik', 'Владислав Варненчик', 'Vladislav Varnenchik', ''),
    ('kaysieva-gradina', 'Кайсиева градина', 'Kaysieva Gradina', ''),
    ('pogrebi', 'Погреби', 'Pogrebi', ''),
    ('gratska-mahala', 'Гръцка махала', 'Gratska Mahala', ''),
    ('kolhozen-pazar', 'Колхозен пазар', 'Kolhozen Pazar', ''),
    ('tsveten-kvartal', 'Цветен квартал', 'Tsveten Kvartal', ''),
    ('chataldzha', 'Чаталджа', 'Chataldzha', ''),
] + [(f'mladost-{i}', f'Младост {i}', f'Mladost {i}', '') for i in range(1, 3)] + [
    (f'vazrazhdane-{i}', f'Възраждане {i}', f'Vazrazhdane {i}', '') for i in range(1, 5)
]


def seed(apps, using='default'):
    Country = apps.get_model('market', 'Country')
    City = apps.get_model('market', 'City')
    Neighbourhood = apps.get_model('market', 'Neighbourhood')
    Alias = apps.get_model('market', 'NeighbourhoodAlias')
    country, _ = Country.objects.using(using).get_or_create(code='BG', defaults={'name': 'Bulgaria'})
    for slug, bg, en, quarters in [('varna', 'Варна', 'Varna', VARNA), ('sofia', 'София', 'Sofia', SOFIA)]:
        city, _ = City.objects.using(using).get_or_create(slug=slug, defaults={
            'country': country, 'name_bg': bg, 'name_en': en})
        for key, bg_name, en_name, extra in quarters:
            neighbourhood, _ = Neighbourhood.objects.using(using).get_or_create(
                city=city, slug=key, defaults={'name_bg': bg_name, 'name_en': en_name})
            for alias in [bg_name, en_name, key, *extra.split('|')]:
                if alias:
                    Alias.objects.using(using).get_or_create(neighbourhood=neighbourhood,
                        normalized_alias=normalize(alias), defaults={'alias': alias})


def contains(text, token):
    return f' {token} ' in f' {text} '


def resolve_values(offer, cities, aliases):
    raw = offer.location_raw or offer.location or ''
    text = normalize(' '.join(filter(None, [offer.location, offer.location_raw])))
    primary = normalize(offer.location)
    supported_names = {normalize(n) for c in cities for n in (c.slug, c.name_bg, c.name_en)}
    outside = any(contains(primary, token) for token in OUTSIDE - supported_names)
    matches = {c.pk for c in cities if not outside and any(contains(text, normalize(n)) for n in (c.slug, c.name_bg, c.name_en))}
    city_id = next(iter(matches)) if len(matches) == 1 else None
    method = 'city_text' if city_id else 'unresolved'
    evidence = offer.evidence if isinstance(offer.evidence, dict) else {}
    if not matches and not outside:
        context = evidence.get('city')
        if not text and evidence.get('crawler') == 'crawl_live':
            context = context or 'varna'
        city_id = next((c.pk for c in cities if c.slug == context), None)
        if city_id:
            method = 'source_city'
    candidates = [(token, pk) for token, pk in aliases.get(city_id, []) if contains(text, token)
                  and (token not in {'bulgaria', 'balgariya'} or any(
                      contains(text, f'{prefix} {token}') for prefix in ('kv', 'zh k', 'kvartal', 'district')))]
    # Longer aliases win only if shorter matches are contained within them:
    # Mladost 1A must not become Mladost 1; two independent quarters are ambiguous.
    candidates = [(token, pk) for token, pk in candidates
                  if not any(token != other and contains(other, token) for other, _ in candidates)]
    ids = {pk for _, pk in candidates}
    neighbourhood_id = next(iter(ids)) if len(ids) == 1 else None
    return {'city_id': city_id, 'neighbourhood_id': neighbourhood_id,
            'raw_location': raw, 'normalized_location': text,
            'confidence': '0.95' if neighbourhood_id else ('0.40' if city_id else '0.00'),
            'matched_by': 'alias' if neighbourhood_id else method}


def catalogue(apps, using='default'):
    cities = list(apps.get_model('market', 'City').objects.using(using).all())
    aliases = {}
    for city_id, token, pk in apps.get_model('market', 'NeighbourhoodAlias').objects.using(using).filter(
            neighbourhood__active=True).values_list('neighbourhood__city_id', 'normalized_alias', 'neighbourhood_id'):
        aliases.setdefault(city_id, []).append((token, pk))
    return cities, aliases


def backfill(apps, using='default', resolve=False):
    Offer = apps.get_model('sourcing', 'Offer')
    Geo = apps.get_model('market', 'OfferGeo')
    cities, aliases = catalogue(apps, using)
    offers = Offer.objects.using(using).all()
    if not resolve:
        offers = offers.filter(geo__isnull=True)
    count = 0
    for offer in offers.iterator(chunk_size=500):
        values = resolve_values(offer, cities, aliases)
        geo, created = Geo.objects.using(using).get_or_create(offer_id=offer.pk, defaults=values)
        if resolve and not created and geo.matched_by != 'manual':
            Geo.objects.using(using).filter(pk=geo.pk).update(**values)
        count += 1
    return count
