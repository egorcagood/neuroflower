"""Deterministic Russian speech from the same snapshot as Telegram. No API or I/O."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import math
from zoneinfo import ZoneInfo

MOSCOW=ZoneInfo('Europe/Moscow')
ONES=('ноль','один','два','три','четыре','пять','шесть','семь','восемь','девять','десять','одиннадцать','двенадцать','тринадцать','четырнадцать','пятнадцать','шестнадцать','семнадцать','восемнадцать','девятнадцать')
TENS=('','','двадцать','тридцать','сорок','пятьдесят','шестьдесят','семьдесят','восемьдесят','девяносто')
HUNDREDS=('','сто','двести','триста','четыреста','пятьсот','шестьсот','семьсот','восемьсот','девятьсот')
GEN=('нуля','одного','двух','трёх','четырёх','пяти','шести','семи','восьми','девяти','десяти','одиннадцати','двенадцати','тринадцати','четырнадцати','пятнадцати','шестнадцати','семнадцати','восемнадцати','девятнадцати')
GENTENS=('','','двадцати','тридцати','сорока','пятидесяти','шестидесяти','семидесяти','восьмидесяти','девяноста')
MONTHS=('','января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря')
DAYS=('','первого','второго','третьего','четвёртого','пятого','шестого','седьмого','восьмого','девятого','десятого','одиннадцатого','двенадцатого','тринадцатого','четырнадцатого','пятнадцатого','шестнадцатого','семнадцатого','восемнадцатого','девятнадцатого','двадцатого')

def ending(n,forms):
    n=abs(n)
    return forms[2] if 11<=n%100<=14 else forms[0] if n%10==1 else forms[1] if 2<=n%10<=4 else forms[2]

def cardinal(n,female=False):
    if type(n) is not int or abs(n)>999999:raise ValueError('bounded_number_required')
    if n<0:return 'минус '+cardinal(-n,female)
    if n>=1000:
        k,rest=divmod(n,1000)
        return cardinal(k,True)+' '+ending(k,('тысяча','тысячи','тысяч'))+(' '+cardinal(rest,female) if rest else '')
    words=[]
    if n>=100:words.append(HUNDREDS[n//100]);n%=100
    if n>=20:words.append(TENS[n//10]);n%=10
    if n or not words:words.append(('одна' if n==1 else 'две') if female and n in (1,2) else ONES[n])
    return ' '.join(words)

def genitive(n):
    if n<0:return 'минус '+genitive(-n)
    if n<20:return GEN[n]
    return GENTENS[n//10]+(' '+GEN[n%10] if n%10 else '')

def quantity(n,forms):return cardinal(n)+' '+ending(n,forms)

def rounded(n):return int(Decimal(str(n)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))

def valid(value,lo,hi):
    return type(value) in (int,float) and math.isfinite(value) and lo<=value<=hi

def decimal_words(value,unit):
    value=Decimal(str(value)).quantize(Decimal('.1'),rounding=ROUND_HALF_UP)
    n=abs(int(value*10));whole,tenth=divmod(n,10)
    return ('минус ' if value<0 else '')+cardinal(whole,True)+' '+ending(whole,('целая','целых','целых'))+' '+cardinal(tenth,True)+' '+ending(tenth,('десятая','десятых','десятых'))+' '+unit

def readings_speech(snap,precise=False):
    row=snap.get('reading')
    if not row or snap.get('stale',True):
        return 'Свежих показаний пока нет, кожаный. Проверь, включена ли плата. Про нынешнее самочувствие гадать не буду.'
    parts=[];raw=row.get('soil_raw');index=snap.get('relative_moisture')
    if not valid(raw,0,4095):parts.append('О почве нет данных.')
    elif not 30<=raw<=4065:parts.append('Проверь датчик почвы.')
    elif not snap.get('calibrated') or not valid(index,0,100):parts.append('Шкала почвы ещё не настроена.')
    else:parts.append('Почва по моей шкале — '+cardinal(rounded(index))+' из ста.')
    light=row.get('light_lux')
    if not valid(light,0,200000):parts.append('О свете нет данных.')
    elif precise:parts.append('Свет — '+decimal_words(light,'люкса')+'.')
    elif light<1:parts.append('Сейчас темно.')
    else:
        n=rounded(light) if light<1000 else rounded(light/100)*100
        parts.append('Свет — примерно '+quantity(n,('люкс','люкса','люкс'))+'.')
    temp=row.get('temperature_C')
    if valid(temp,-50,85):
        n=abs(rounded(temp))
        parts.append(('Температура — '+decimal_words(temp,'градуса') if precise else 'Около '+genitive(rounded(temp))+(' градуса' if n%10==1 and n%100!=11 else ' градусов'))+'.')
    else:parts.append('Температуру пока не знаю.')
    humidity=row.get('air_RH_pct')
    if valid(humidity,0,100):
        parts.append('Влажность воздуха — '+(decimal_words(humidity,'процента') if precise else quantity(rounded(humidity),('процент','процента','процентов')))+'.')
    else:parts.append('О влажности воздуха нет данных.')
    return ' '.join(parts)

def watering_speech(waters,now):
    if not waters:return 'Записей о поливах пока нет, кожаный.'
    at=waters[0].get('at')
    if not valid(at,0,4102444800):return 'Дата полива в памяти непонятная. Проверь её в Telegram.'
    if at>now:return 'Дата полива записана в будущем. Проверь её в Telegram.'
    date=datetime.fromtimestamp(at,MOSCOW);today=datetime.fromtimestamp(now,MOSCOW)
    delta=(today.date()-date.date()).days
    part='ночью' if date.hour<6 else 'утром' if date.hour<12 else 'днём' if date.hour<18 else 'вечером'
    if delta in (0,1):when=('сегодня' if delta==0 else 'вчера')+' '+part
    else:
        day=DAYS[date.day] if date.day<=20 else ('двадцать '+DAYS[date.day-20] if date.day<30 else 'тридцатого' if date.day==30 else 'тридцать первого')
        when=day+' '+MONTHS[date.month]
        if date.year==today.year-1:when+=' в прошлом году'
        elif date.year!=today.year:when+='; '+quantity(today.year-date.year,('год','года','лет'))+' назад'
    return 'По моей памяти, поливали меня '+when+'.'
