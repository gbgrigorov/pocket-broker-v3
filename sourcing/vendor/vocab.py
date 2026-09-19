# -*- coding: utf-8 -*-
"""Multilingual vocabulary for normalising 30+ differently-shaped price lists.

Headers arrive in Bulgarian, Russian, English and German, often abbreviated.
Everything here is matched against a casefolded, punctuation-stripped header.
"""

# --- canonical field -> header aliases (substring match, longest wins) -------
FIELD_ALIASES = {
    'ref': ['id', '№', 'no', 'номер', 'ref', 'ref №', 'реф', 'код', 'лот', 'лот на сайте',
            'ап-т номер', 'apartment no', 'обект'],
    'status': ['статус', 'status', 'статут', 'состояние', 'sold', 'available', 'наличие'],
    'location': ['локация', 'локация/град', 'град', 'города', 'город', 'city', 'area', 'place',
                 'населено място', 'нас. място', 'населенное место', 'местоположение',
                 'курорт', 'resort', 'ort', 'region', 'район', 'location apartments', 'location',
                 'място', 'място', 'место', 'градче', 'селище'],
    'complex': ['комплекс', 'complex', 'compex', 'наименование', 'название', 'name', 'объект',
                'обекти', 'апартамент', 'апартаменты', 'building', 'сграда', 'projekt'],
    'type': ['тип', 'вид имот', 'вид недвижимости', 'тип недвижимости', 'тип апартамента',
             'тип апартамент', 'type', 'typ', 'кол-во комнат', 'количество комнат', 'комнат',
             'room', 'rooms', 'спални', 'спальни', 'брой спални', 'bedrooms', 'bedroom', 'beds'],
    'floor': ['етаж', 'ет.', 'ет', 'этаж', 'floor', 'stock', 'ниво'],
    'area': ['площ', 'площ кв.м.', 'площ (кв.м.)', 'площадь', 'общая площадь', 'обща площ',
             'застроена площ', 'кв.м', 'кв. м', 'кв/м', 'sq/m', 'sqm', 'm2', 'м2', 'кв.м.',
             'area', 'size', 'total area', 'fläche', 'метраж', 'квадрати'],
    'price': ['цена', 'цена €', 'цена eur', 'цена, eur', 'цена в €', 'price', 'preis',
              'стоимость', 'цена (€)', 'price €', 'цена €'],
    'price_m2': ['€/м²', 'цена на кв.м', 'цена м2', 'цена, eur, за кв.м.', 'price per m2',
                 'цена на кв.м./ eur', '€/m2'],
    'commission': ['комисион', 'комисиона', 'комисионна', 'комисиони', 'комиссия', 'комиссии',
                   'commission', 'comission', 'comis', 'provision', 'комиссия агентству',
                   'комиссия для коллег', 'included comission', 'комисион за партньори',
                   'comission for you', 'комиссиони', 'комисионни', 'included commision',
                   'included commission', 'commision', 'комиссия для агентств',
                   'комиссия агенту', 'partner fee', 'agent fee', 'комисион за вас'],
    'maintenance': ['такса', 'такса поддръжка', 'такса поддержки', 'таксa', 'maintenance',
                    'maint.fee', 'maintenance fee', 'annual fee', 'поддръжка', 'поддержка',
                    'такса €', 'такса обслуживания', 'общи части', 'support fee'],
    'view': ['гледка', 'изглед', 'вид', 'вид из окон', 'view', 'aussicht', 'гледка към'],
    'furnished': ['мебели', 'мебель', 'меблировка', 'обзавеждане', 'furnished', 'furniture',
                  'möbliert', 'мебел'],
    'photos': ['снимки', 'снимка', 'фото', 'фотографии', 'photo', 'photos', 'foto', 'bilder',
               'ссылка на фото', 'снимки и описание', 'фото/видео', 'изображения'],
    'video': ['видео', 'video', 'videos'],
    'notes': ['коментар', 'коментари', 'комментарии', 'забележка', 'примечание', 'бележки',
              'notes', 'note', 'comments', 'comment', 'описание', 'details', 'детали',
              'для пометок', 'bemerkung'],
    'documents': ['акт 16', 'акт16', 'act 16', 'ready docs', 'документи', 'документы', 'акт'],
    'manager': ['мениджър', 'менеджер', 'manager', 'агент', 'agent', 'контакт'],
    'deal': ['сделка', 'наем', 'под наем', 'rent', 'sale', 'продажба', 'аренда'],
}

# --- Black Sea gazetteer: used to tell a "location" section row from a --------
#     "type" section row, and to canonicalise 5 spellings of one resort.
LOCATIONS = {
    'Бургас': ['бургас', 'burgas', 'burgaz'],
    'Слънчев бряг': ['слънчев бряг', 'слънев бряг', 'слънчев', 'солнечный берег', 'sunny beach',
                     'sunnybeach', 'с.бряг', 'сл.бряг', 'слънчев бр'],
    'Свети Влас': ['свети влас', 'св.влас', 'св. влас', 'святой влас', 'sveti vlas', 'st.vlas',
                   'st. vlas', 'stvlas', 'св влас', 'saint vlas', 'st vlas', 'sv.vlas', 'sv vlas'],
    'Несебър': ['несебър', 'несебр', 'несебыр', 'nesebar', 'nessebar', 'nesebur', 'ст.несебър',
                'стар несебър', 'old nessebar'],
    'Равда': ['равда', 'ravda'],
    'Поморие': ['поморие', 'pomorie'],
    'Созопол': ['созопол', 'sozopol'],
    'Приморско': ['приморско', 'primorsko'],
    'Царево': ['царево', 'tsarevo', 'carevo'],
    'Ахтопол': ['ахтопол', 'ahtopol'],
    'Синеморец': ['синеморец', 'sinemorets'],
    'Лозенец': ['лозенец', 'lozenets'],
    'Китен': ['китен', 'kiten'],
    'Черноморец': ['черноморец', 'chernomorets'],
    'Елените': ['елените', 'елените.', 'elenite'],
    'Ахелой': ['ахелой', 'aheloy', 'acheloy'],
    'Обзор': ['обзор', 'obzor'],
    'Бяла': ['бяла', 'byala', 'biala'],
    'Свети Никола': ['свети никола', 'sveti nikola'],
    'Варна': ['варна', 'varna'],
    'Златни пясъци': ['златни пясъци', 'золотые пески', 'golden sands'],
    'Св. Константин и Елена': ['св. константин', 'константин и елена', 'saints constantine'],
    'Албена': ['албена', 'albena'],
    'Балчик': ['балчик', 'balchik'],
    'Каварна': ['каварна', 'kavarna'],
    'Шкорпиловци': ['шкорпиловци', 'shkorpilovtsi'],
    'Дюни': ['дюни', 'duni'],
    'Кошарица': ['кошарица', 'kosharitsa', 'kosharitca', 'kosharica'],
    'Тънково': ['тънково', 'tankovo'],
    'Сарафово': ['сарафово', 'sarafovo'],
    'Крайморие': ['крайморие', 'kraymorie'],
    'Свети Тома': ['свети тома'],
    'София': ['софия', 'sofia'],
}

# --- property type -> bedroom count -----------------------------------------
# Bulgarian/Russian convention: "двустаен"/"2-комнатная" = 2 rooms = 1 bedroom.
TYPE_BEDROOMS = [
    (['студио', 'студия', 'studio', 'stuido', 'ателие', 'atelier'], 0),
    (['едностаен', 'однокомнат', '1-комнат', '1 комнат', 'one room'], 0),
    (['двустаен', 'двухкомнат', '2-комнат', '2 комнат', '1 спалня', '1спалня', '1 спальня',
      '1 bedroom', '1bedroom', '1 bed', '1-bed', 'one bedroom', '1 br'], 1),
    (['тристаен', 'трехкомнат', 'трёхкомнат', '3-комнат', '3 комнат', '2 спални', '2 спальни',
      '2 bedroom', '2 bed', '2-bed', 'two bedroom', '2 br'], 2),
    (['четиристаен', 'четырехкомнат', '4-комнат', '3 спални', '3 спальни', '3 bedroom',
      '3 bed', '3-bed', 'three bedroom', '3 br'], 3),
    (['4 спални', '4 спальни', '4 bedroom', '4 bed', '4-bed'], 4),
    (['5 спални', '5 bedroom', '5 bed'], 5),
]

RENT_WORDS = ['под наем', 'подnaem', 'наем', 'аренда', 'аренду', 'for rent', 'rental',
              'на месец', 'в месяц', 'per month', '/мес', 'сезонен', 'сезонность', 'seasonal',
              'краткосрочн', 'долгосрочн', 'miete']

PARKING_WORDS = ['парко място', 'паркомясто', 'паркомместо', 'парко-място', 'parking',
                 'паркинг', 'гараж', 'garage', 'парковочное', 'парко мест', 'парко-мест',
                 'машиномест', 'паркомест']

# property kind -> the words that signal it, in every language the sheets use.
# The canonical key is what the UI shows, so one flat is never 'къща' and
# another 'house'.
KIND_WORDS = {
    'house':      ['къща', 'кыща', 'дом ', 'дом,', 'house', 'частный дом', 'къщa'],
    'villa':      ['вила', 'villa', 'вилла'],
    'townhouse':  ['таунхаус', 'townhouse', 'таун хаус'],
    'maisonette': ['мезонет', 'maisonette', 'мезонин'],
    'penthouse':  ['пентхаус', 'penthouse', 'пентхауз'],
    'land':       ['парцел', 'land', 'земя', 'plot', 'участок', 'земельный'],
    'office':     ['офис', 'office', 'кабинет'],
    'shop':       ['магазин', 'shop', 'търговски', 'коммерческ', 'commercial'],
    'hotel':      ['хотел', 'hotel', 'гостиниц'],
}

STATUS_MAP = [
    (['продано', 'продадено', 'sold', 'verkauft'], 'sold'),
    (['резерв', 'reserved', 'депозит', 'deposit', 'капаро'], 'reserved'),
    (['активен', 'active', 'свободно', 'свободен', 'available', 'frei', 'нов', 'new'], 'active'),
    (['снят', 'снето', 'withdrawn', 'оттеглен'], 'withdrawn'),
]

YES = ['да', 'yes', 'ja', 'есть', 'има', 'y', '+', 'обзаведен', 'furnished', 'мебели',
       'нови мебели', 'частично']
NO = ['не', 'no', 'нет', 'няма', 'nein', '-', 'без мебели', 'unfurnished']

# section rows that describe a *type* group rather than a location
TYPE_SECTIONS = ['studio', 'студио', 'bed', 'спалн', 'спальн', 'комнат', 'house', 'къщ',
                 'villa', 'вил', 'apartment', 'апартамент', 'penthouse', 'maisonette']
