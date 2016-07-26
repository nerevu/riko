# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab

from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from pprint import pprint
from riko import get_path
from riko.bado import coroutine
from riko.lib.utils import combine_dicts as cdict
from riko.collections.sync import SyncCollection
from riko.collections.async import AsyncCollection


def make_regex(field, match, replace, default=None):
    result = {
        'field': field, 'match': match, 'replace': replace, 'default': default}

    return result


def make_simplemath(other, op):
    return {'other': {'subkey': other, 'type': 'number'}, 'op': op}


DEF_CUR_CODE = 'USD'
pmatch = {'seriesmatch': False}
smatch = {'singlematch': True}

subelement_conf = {'path': 'content.value', 'token_key': None}
rename1_rule = [
    {'newval': 'k:marketplace', 'field': 'link', 'copy': True},
    {'newval': 'k:job_type', 'field': 'description', 'copy': True},
    {'newval': 'k:content', 'field': 'description', 'copy': True},
    {'newval': 'k:submissions', 'field': 'description', 'copy': True},
    {'newval': 'k:author', 'field': 'title', 'copy': True},
    {'newval': 'k:work_location', 'field': 'description', 'copy': True},
    {'newval': 'k:client_location', 'field': 'description', 'copy': True},
    {'newval': 'k:tags', 'field': 'description', 'copy': True},
    {'newval': 'k:due', 'field': 'description', 'copy': True},
    {'newval': 'k:budget_raw', 'field': 'description', 'copy': True},
    {'newval': 'k:posted', 'field': 'updated'},
    # # {'newval': 'k:category', 'field': 'description', 'copy': True},
]

rename2_rule = [
    {'newval': 'k:parsed_type', 'field': 'k:budget_raw', 'copy': True},
    {'newval': 'k:budget_raw1', 'field': 'k:budget_raw', 'copy': True},
    {'newval': 'k:budget_raw2', 'field': 'k:budget_raw', 'copy': True}]

rename3_rule = [
    {'newval': 'k:budget_raw1_num', 'field': 'k:budget_raw1', 'copy': True},
    {'newval': 'k:budget_raw1_sym', 'field': 'k:budget_raw1', 'copy': True},
    {'newval': 'k:budget_raw1_code', 'field': 'k:budget_raw1', 'copy': True},
    {'newval': 'k:budget_raw2_num', 'field': 'k:budget_raw2', 'copy': True},
    {'newval': 'k:budget_raw2_sym', 'field': 'k:budget_raw2', 'copy': True},
    {'newval': 'k:budget_raw2_code', 'field': 'k:budget_raw2', 'copy': True}]

rename4_rule = [
    {'newval': 'k:budget_full', 'field': 'k:budget_w_sym', 'copy': True}]

rename5_rule = [
    {'field': 'pubDate'},
    {'field': 'summary'},
    {'field': 'content'},
    {'field': 'dc:creator'},
    {'field': 'updated_parsed'},
    {'field': 'k:budget_raw'},
    {'field': 'k:budget_raw1'},
    {'field': 'k:budget_raw1_code'},
    {'field': 'k:budget_raw1_num'},
    {'field': 'k:budget_raw1_sym'},
    {'field': 'k:budget_raw2'},
    {'field': 'k:budget_raw2_code'},
    {'field': 'k:budget_raw2_num'},
    {'field': 'k:budget_raw2_sym'},
    {'field': 'k:budget_sym'},
    {'field': 'y:title'},
    {'field': 'y:published'},
    {'field': 'y:id'}]

match1_01 = r'(.*)( - oDesk|\| Elance Job)'
match1_02 = r'^(http[s]?:\/\/)?\/?([^\/\.]+\.)*([^\/\.]+\.[^:\/\s\.]{2,3})(.*)'
match1_03 = r'.*(Hourly budget:|Budget:<.*?> Hourly).*'
match1_04 = r'.*(Fixed Price budget:|Budget:<.*?> Fixed Price).*'
match1_05 = r'^(?!\b(hourly|fixed)\b).*'
match1_06 = r'.*?[Description]?.*?<.*?>(.*?)\s*?<.*?>.*'
match1_08 = r'(.*)(<b>Proposals:<.*?>).*?(\d+).*?(<a href)(.*)'
match1_11 = r'(.*)(\bby\b)(.*)'
match1_13 = r'(.*)((Freelancer|Preferred Job) Location:<.*?>)(.*?)(<.*?>)(.*)'
m1_14 = 'Client Location:<.*?>|Country<.*?>:'
match1_14 = r'(.*)(%s).*?(\w.*?)\s*?(<.*?>)(.*)' % m1_14
match1_15 = r'(.*)(<b>(Category:?<.*?>:?))(.*?)(<.*?>|<b>Skills<.*?>)(.*)'
match1_16 = r'(.*)(<b>(Required skills|Desired Skills):<.*?>)(.*?)(<.*?>)(.*)'
match1_17 = r'(.*)(Jobs:)(.*?)(\))(.*)'
match1_18 = r'&gt;|<br>'
match1_19 = r'(\w+)(?!.*,)'
match1_20 = r'\/|\s*&amp;'
match1_21 = r'[^\w|\-,]+'
match1_23 = r'.*Time Left.*Ends\s*?(.*?)\)?\s*?<.*?>.*'
m1_24 = 'Fixed Price budget:<.*?>|Hourly budget.*Rate:|Fixed Price\s+\('
match1_24 = r'(.*)(%s)(.*?)\)*(<.*?>|, Jobs:)(.*)' % m1_24
match1_25 = r'Under|Upto|Less than|or less'
match1_26 = r'^(?!.*-.*)(.*)'

regex1_rule = [
    make_regex('title', match1_01, '$1'),
    make_regex('k:marketplace', match1_02, '$3'),
    make_regex('k:job_type', match1_03, 'hourly'),
    make_regex('k:job_type', match1_04, 'fixed'),
    make_regex('k:job_type', match1_05, 'unknown'),
    cdict(smatch, make_regex('k:content', match1_06, '$1', 'N/A')),
    make_regex('k:submissions', match1_08, '$3', 'unknown'),
    make_regex('k:author', match1_11, '$3', 'unknown'),
    make_regex('k:work_location', match1_13, '$4', 'unknown'),
    make_regex('k:client_location', match1_14, '$3', 'unknown'),
    cdict(pmatch, make_regex('k:tags', match1_15, '$4')),
    cdict(pmatch, make_regex('k:tags', match1_16, '$4')),
    cdict(pmatch, make_regex('k:tags', match1_17, '$3')),
    cdict(make_regex('k:tags', match1_18, ',')),
    # cdict(make_regex('k:tags', match1_19, '$1,')),
    make_regex('k:tags', match1_20, ','),
    make_regex('k:tags', match1_21, '-'),
    make_regex('k:tags', '^-|-$', ''),
    make_regex('k:tags', '-,-|,-|-,', ','),
    make_regex('k:tags', '^,|,$', ''),
    make_regex('k:due', match1_23, '$1', 'unknown'),
    make_regex('k:budget_raw', match1_24, '$3', '0'),
    make_regex('k:budget_raw', 'k', '000'),
    make_regex('k:budget_raw', 'Under|Upto|Less than', '0 -'),
    make_regex('k:budget_raw', 'or less', '- 0'),
    make_regex('k:budget_raw', r'.*Not Sure.*', '0'),
    make_regex('k:budget_raw', match1_25, '-'),
    make_regex('k:budget_raw', match1_26, '$1 - $1'),
]

regex2_rule = [
    make_regex('k:budget_raw1', '(.*)-(.*)', '$1'),
    make_regex('k:budget_raw2', '(.*)-(.*)', '$2')
]

regex3_rule = [
    make_regex('k:budget_raw1_num', r'[,.\s]', ''),
    make_regex('k:budget_raw1_num', r'[^\d]*(\d+).*', '$1'),
    make_regex('k:budget_raw1_sym', r'.*([$£€₹]).*', '$1'),
    make_regex('k:budget_raw1_code', r'.*(\b[A-Z]{3}\b).*', '$1', ''),
    make_regex('k:budget_raw2_num', r'[,.\s]', ''),
    make_regex('k:budget_raw2_num', r'[^\d]*(\d+).*', '$1'),
    make_regex('k:budget_raw2_sym', r'.*([$£€₹]).*', '$1'),
    make_regex('k:budget_raw2_code', r'.*(\b[A-Z]{3}\b).*', '$1', ''),
    make_regex('k:parsed_type', r'.*hr.*', 'hourly'),
    make_regex('k:parsed_type', r'.*unknown.*', 'unknown'),
    make_regex('k:parsed_type', r'.*(?!(hourly|unknown)).*', 'fixed')
]

strreplace_rule = {'find': 'unknown', 'replace': {'subkey': 'k:parsed_type'}}

strreplace2_rule = [
    {'find': '$', 'replace': 'USD'},
    {'find': '£', 'replace': 'GBP'},
    {'find': '€', 'replace': 'EUR'},
    {'find': '₹', 'replace': 'INR'},
]

regex4_rule = make_regex('k:cur_code', r'^(?![A-Z]{3}\b)(.*)', DEF_CUR_CODE)
regex5_conf = {
    'rule': [
        make_regex('k:job_type', 'fixed', '1'),
        make_regex('k:job_type', 'hourly', '2'),
        make_regex('k:job_type', 'unknown', '3')
    ]
}

strconcat1_conf = {
    'part': [
        {'subkey': 'k:budget_raw1_code'}, {'subkey': 'k:budget_raw2_code'}]}

strconcat2_conf = {
    'part': [{'subkey': 'k:budget_raw1_sym'}, {'subkey': 'k:budget_raw2_sym'}]}

strconcat3_conf = {
    'part': [
        {'subkey': 'k:budget_w_sym'},
        {'value': ' ('},
        {'subkey': 'k:budget_converted_w_sym'},
        {'value': ')'}]}

strconcat4_conf = {'part': [{'subkey': 'k:budget_full'}, {'value': ' / hr'}]}
tokenizer_conf = {'dedupe': True, 'sort': True}
substring1_conf = {'from': 0, 'length': 3}
substring2_conf = {'from': 0, 'length': 1}
currencyformat1_conf = {'currency': {'subkey': 'k:cur_code'}}
exchangerate_conf = {'url': get_path('quote.json')}
currencyformat2_conf = {'currency': DEF_CUR_CODE}
simplemath1_conf = make_simplemath('k:budget_raw2_num', 'mean')
simplemath2_conf = make_simplemath('k:rate', 'multiply')
test1 = lambda item: item.get('k:cur_code')
test2 = lambda item: item.get('k:cur_code') != DEF_CUR_CODE
test3 = lambda item: item.get('k:cur_code') == DEF_CUR_CODE
test4 = lambda item: item.get('k:job_type') != 'hourly'

sources = [
    {'url': get_path('kazeeki_1.json'), 'type': 'fetchdata', 'path': 'items'},
    {'url': get_path('kazeeki_2.json'), 'type': 'fetchdata', 'path': 'items'},
    {'url': get_path('kazeeki_3.json'), 'type': 'fetchdata', 'path': 'items'},
]


def parse_source(source):
    pipe = (source
        .subelement(conf=subelement_conf, emit=False, assign='content')
        .rename(conf={'rule': rename1_rule})
        .regex(conf={'rule': regex1_rule})
        .rename(conf={'rule': rename2_rule})
        .regex(conf={'rule': regex2_rule})
        .rename(conf={'rule': rename3_rule})
        .regex(conf={'rule': regex3_rule})
        .strreplace(
            conf={'rule': strreplace_rule},
            field='k:job_type',
            assign='k:job_type')
        .strtransform(
            conf={'rule': {'transform': 'lower'}},
            field='k:tags', assign='k:tags')
        .tokenizer(conf=tokenizer_conf, field='k:tags', assign='k:tags')
        .simplemath(
            conf=simplemath1_conf,
            field='k:budget_raw1_num',
            assign='k:budget')
        .strconcat(conf=strconcat1_conf, assign='k:cur_code')
        .substr(conf=substring1_conf, field='k:cur_code', assign='k:cur_code')
        .strconcat(
            conf=strconcat2_conf,
            field='k:budget_sym',
            assign='k:budget_sym')
        .substr(
            conf=substring2_conf,
            field='k:budget_sym',
            assign='k:budget_sym')
        .strreplace(
            conf={'rule': strreplace2_rule},
            field='k:budget_sym',
            assign='k:cur_code',
            skip_if=test1)
        .regex(conf={'rule': regex4_rule})
        .regex(conf=regex5_conf, assign='k:job_type_code')
        .hash(field='content', assign='id')
        .currencyformat(
            conf=currencyformat1_conf,
            field='k:budget',
            assign='k:budget_w_sym')
        .exchangerate(
            conf=exchangerate_conf,
            field='k:cur_code',
            assign='k:rate')
        .simplemath(
            conf=simplemath2_conf,
            field='k:budget',
            assign='k:budget_converted')
        .currencyformat(
            conf=currencyformat2_conf,
            field='k:budget_converted',
            assign='k:budget_converted_w_sym')
        .rename(conf={'rule': rename4_rule}, skip_if=test2)
        .strconcat(conf=strconcat3_conf, assign='k:budget_full', skip_if=test3)
        .strconcat(conf=strconcat4_conf, field='k:budget_full', skip_if=test4)
        .rename(conf={'rule': rename5_rule}))

    return pipe.list


def pipe(test=False):
    source = SyncCollection(sources).pipe(test=test)
    stream = parse_source(source)
    pprint(stream[-1])
    return stream


@coroutine
def async_pipe(reactor, test=None):
    source = AsyncCollection(sources).async_pipe(test=test)
    stream = yield parse_source(source)
    pprint(stream[-1])
