# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab

from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from pprint import pprint
from functools import partial

from riko import get_path
from riko.bado import coroutine
from riko.collections import SyncPipe, AsyncPipe

BR = {'find': '<br>'}
DEF_CUR_CODE = 'USD'

odesk_conf = {'url': get_path('odesk.json'), 'path': 'items'}
guru_conf = {'url': get_path('guru.json'), 'path': 'items'}
elance_conf = {'url': get_path('elance.json'), 'path': 'items'}
freelancer_conf = {'url': get_path('freelancer.json'), 'path': 'items'}


def make_regex(field, match, replace, default=None):
    result = {
        'field': field, 'match': match, 'replace': replace, 'default': default}

    return result


def make_simplemath(other, op):
    return {'other': {'subkey': other, 'type': 'number'}, 'op': op}


def add_source(source):
    subelement_conf = {'path': 'k:source.content.1', 'token_key': None}

    sourced = (source
        .urlparse(field='link', assign='k:source')
        .subelement(conf=subelement_conf, emit=False, assign='k:source'))

    return sourced


def add_id(source, rule, field='link'):
    make_id_part = [{'subkey': 'k:source'}, {'value': '-'}, {'subkey': 'id'}]

    ideed = (source
        .strfind(conf={'rule': rule}, field=field, assign='id')
        .strconcat(conf={'part': make_id_part}, assign='id'))

    return ideed


def add_posted(source, rule='', field='summary'):
    if rule:
        conf = {'rule': rule}
        source = source.strfind(conf=conf, field=field, assign='k:posted')
    else:
        rule = {'field': 'updated', 'newval': 'k:posted'}
        source = source.rename(conf={'rule': rule})

    return source


def add_tags(source, rule, field='summary', assign='k:tags'):
    tokenizer_conf = {'dedupe': True, 'sort': True}
    no_tags = {'field': assign}

    tag_strreplace_rule = [
        {'find': '  ', 'replace': ','},
        {'find': '&gt;', 'replace': ','},
        {'find': '&amp;', 'replace': '&'},
        {'find': 'Other -', 'replace': ''},
        # {'find': '-', 'replace': ''},
    ]

    tagged = (source
        .strfind(conf={'rule': rule}, field=field, assign=assign)
        .strreplace(
            conf={'rule': tag_strreplace_rule}, field=assign,
            assign=assign, skip_if=no_tags)
        .strtransform(
            conf={'rule': {'transform': 'lower'}}, field=assign,
            assign=assign, skip_if=no_tags)
        .tokenizer(
            conf=tokenizer_conf, field=assign, assign=assign, skip_if=no_tags)
    )

    return tagged


def add_budget(source, budget_text, fixed_text='', hourly_text='', double=True):
    codes = '$£€₹'
    no_raw_budget = {'field': 'k:budget_raw'}
    has_code = {'field': 'k:cur_code', 'include': True}
    is_def_cur = {'field': 'k:cur_code', 'text': DEF_CUR_CODE, 'include': True}
    not_def_cur = {'field': 'k:cur_code', 'text': DEF_CUR_CODE}
    isnt_fixed = {'field': 'summary', 'text': fixed_text}
    isnt_hourly = {'field': 'summary', 'text': hourly_text}
    no_symbol = {'field': 'k:budget_raw', 'text': codes, 'op': 'intersection'}
    code_or_no_raw_budget = [has_code, no_raw_budget]
    def_cur_or_no_raw_budget = [is_def_cur, no_raw_budget]
    not_def_cur_or_no_raw_budget = [not_def_cur, no_raw_budget]

    first_num_rule = {'find': r'\d+', 'location': 'at'}
    last_num_rule = {'find': r'\d+', 'location': 'at', 'param': 'last'}
    cur_rule = {'find': r'\b[A-Z]{3}\b', 'location': 'at'}
    sym_rule = {'find': '[%s]' % codes, 'location': 'at'}

    # make_regex('k:budget_raw', r'[(),.\s]', ''),
    invalid_budgets = [
        {'find': 'Less than', 'replace': '0-'},
        {'find': 'Under', 'replace': '0-'},
        {'find': 'Upto', 'replace': '0-'},
        {'find': 'or less', 'replace': '-0'},
        {'find': 'k', 'replace': '000'},
        {'find': 'Not Sure', 'replace': ''},
        {'find': 'Not sure', 'replace': ''},
        {'find': '(', 'replace': ''},
        {'find': ')', 'replace': ''},
        {'find': '.', 'replace': ''},
        {'find': ',', 'replace': ''},
        {'find': ' ', 'replace': ''},
    ]

    cur_strreplace_rule = [
        {'find': '$', 'replace': 'USD'},
        {'find': '£', 'replace': 'GBP'},
        {'find': '€', 'replace': 'EUR'},
        {'find': '₹', 'replace': 'INR'},
    ]

    converted_budget_part = [
        {'subkey': 'k:budget_w_sym'},
        {'value': ' ('},
        {'subkey': 'k:budget_converted_w_sym'},
        {'value': ')'}
    ]

    def_full_budget_part = {'subkey': 'k:budget_w_sym'}
    hourly_budget_part = [{'subkey': 'k:budget_full'}, {'value': ' / hr'}]
    exchangerate_conf = {'url': get_path('quote.json')}
    native_currencyformat_conf = {'currency': {'subkey': 'k:cur_code'}}
    def_currencyformat_conf = {'currency': DEF_CUR_CODE}
    ave_budget_conf = make_simplemath('k:budget_raw2_num', 'mean')
    convert_budget_conf = make_simplemath('k:rate', 'multiply')

    if fixed_text:
        source = source.strconcat(
            conf={'part': {'value': 'fixed'}}, assign='k:job_type',
            skip_if=isnt_fixed)

    if hourly_text:
        source = source.strconcat(
            conf={'part': {'value': 'hourly'}}, assign='k:job_type',
            skip_if=isnt_hourly)

    source = (source
        .refind(
            conf={'rule': cur_rule}, field='k:budget_raw',
            assign='k:cur_code', skip_if=no_raw_budget)
        .strreplace(
            conf={'rule': invalid_budgets}, field='k:budget_raw',
            assign='k:budget_raw', skip_if=no_raw_budget))

    if double:
        source = (source
            .refind(
                conf={'rule': first_num_rule}, field='k:budget_raw',
                assign='k:budget_raw_num', skip_if=no_raw_budget)
            .refind(
                conf={'rule': last_num_rule}, field='k:budget_raw',
                assign='k:budget_raw2_num', skip_if=no_raw_budget)
            .simplemath(
                conf=ave_budget_conf, field='k:budget_raw_num',
                assign='k:budget', skip_if=no_raw_budget)
        )
    else:
        source = source.refind(
            conf={'rule': first_num_rule}, field='k:budget_raw',
            assign='k:budget', skip_if=no_raw_budget)

    source = (source
        .refind(
            conf={'rule': sym_rule}, field='k:budget_raw',
            assign='k:budget_raw_sym', skip_if=no_symbol)
        .strreplace(
            conf={'rule': cur_strreplace_rule}, field='k:budget_raw_sym',
            assign='k:cur_code', skip_if=code_or_no_raw_budget)
        .currencyformat(
            conf=native_currencyformat_conf, field='k:budget',
            assign='k:budget_w_sym', skip_if=no_raw_budget)
        .exchangerate(
            conf=exchangerate_conf, field='k:cur_code', assign='k:rate',
            skip_if=def_cur_or_no_raw_budget)
        .simplemath(
            conf=convert_budget_conf, field='k:budget',
            assign='k:budget_converted', skip_if=def_cur_or_no_raw_budget)
        .currencyformat(
            conf=def_currencyformat_conf, field='k:budget_converted',
            assign='k:budget_converted_w_sym', skip_if=def_cur_or_no_raw_budget)
        .strconcat(
            conf={'part': converted_budget_part}, assign='k:budget_full',
            skip_if=def_cur_or_no_raw_budget)
        .strconcat(
            conf={'part': def_full_budget_part}, assign='k:budget_full',
            skip_if=not_def_cur_or_no_raw_budget)
    )

    if hourly_text:
        source = (source
            .strconcat(
                conf={'part': hourly_budget_part}, assign='k:budget_full',
                skip_if=isnt_hourly)
        )

    return source


def clean_locations(source):
    no_client_loc = {'field': 'k:client_location'}
    no_work_loc = {'field': 'k:work_location'}

    rule = {'find': ', ', 'replace': ''}
    cleaned = (source
        .strreplace(
            conf={'rule': rule}, field='k:client_location',
            assign='k:client_location', skip_if=no_client_loc)
        .strreplace(
            conf={'rule': rule}, field='k:work_location',
            assign='k:work_location', skip_if=no_work_loc)
    )

    return cleaned


def remove_cruft(source):
    remove_rule = [
        {'field': 'author'},
        {'field': 'content'},
        {'field': 'dc:creator'},
        {'field': 'links'},
        {'field': 'pubDate'},
        {'field': 'summary'},
        {'field': 'updated'},
        {'field': 'updated_parsed'},
        {'field': 'y:id'},
        {'field': 'y:title'},
        {'field': 'y:published'},
        {'field': 'k:budget_raw'},
        {'field': 'k:budget_raw2_num'},
        {'field': 'k:budget_raw_num'},
        {'field': 'k:budget_raw_sym'},
    ]

    return source.rename(conf={'rule': remove_rule})


def parse_odesk(source, stream=True):
    budget_text = 'Budget</b>:'
    no_budget = {'field': 'summary', 'text': budget_text}
    raw_budget_rule = [{'find': budget_text, 'location': 'after'}, BR]
    title_rule = {'find': '- oDesk'}
    find_id_rule = [{'find': 'ID</b>:', 'location': 'after'}, BR]
    categ_rule = [{'find': 'Category</b>:', 'location': 'after'}, BR]
    skills_rule = [{'find': 'Skills</b>:', 'location': 'after'}, BR]
    client_loc_rule = [{'find': 'Country</b>:', 'location': 'after'}, BR]
    posted_rule = [{'find': 'Posted On</b>:', 'location': 'after'}, BR]
    desc_rule = [{'find': '<p>', 'location': 'after'}, {'find': '<br><br><b>'}]

    source = (source
        .strfind(conf={'rule': title_rule}, field='title', assign='title')
        .strfind(
            conf={'rule': client_loc_rule}, field='summary',
            assign='k:client_location')
        .strfind(
            conf={'rule': desc_rule}, field='summary', assign='description')
        .strfind(
            conf={'rule': raw_budget_rule}, field='summary',
            assign='k:budget_raw', skip_if=no_budget)
    )

    source = add_source(source)
    source = add_posted(source, posted_rule)
    source = add_id(source, find_id_rule, field='summary')
    source = add_budget(source, budget_text, double=False)
    source = add_tags(source, skills_rule)
    source = add_tags(source, categ_rule, assign='k:categories')
    source = clean_locations(source)
    source = remove_cruft(source)
    return source.output if stream else source


def parse_guru(source, stream=True):
    budget_text = 'budget:</b>'
    fixed_text = 'Fixed Price budget:</b>'
    hourly_text = 'Hourly budget:</b>'

    no_budget = {'field': 'summary', 'text': budget_text}
    isnt_hourly = {'field': 'summary', 'text': hourly_text}
    raw_budget_rule = [{'find': budget_text, 'location': 'after'}, BR]
    after_hourly = {'rule': {'find': 'Rate:', 'location': 'after'}}
    find_id_rule = {'find': '/', 'location': 'after', 'param': 'last'}
    categ_rule = [{'find': 'Category:</b>', 'location': 'after'}, BR]
    skills_rule = [{'find': 'Required skills:</b>', 'location': 'after'}, BR]

    job_loc_conf = {
        'rule': [{'find': 'Freelancer Location:</b>', 'location': 'after'}, BR]}

    desc_conf = {
        'rule': [{'find': 'Description:</b>', 'location': 'after'}, BR]}

    source = (source
        .strfind(conf=job_loc_conf, field='summary', assign='k:work_location')
        .strfind(conf=desc_conf, field='summary', assign='description')
        .strfind(
            conf={'rule': raw_budget_rule}, field='summary',
            assign='k:budget_raw', skip_if=no_budget)
        .strfind(
            conf=after_hourly, field='k:budget_raw', assign='k:budget_raw',
            skip_if=isnt_hourly)
    )

    kwargs = {'fixed_text': fixed_text, 'hourly_text': hourly_text}
    source = add_source(source)
    source = add_posted(source)
    source = add_id(source, find_id_rule)
    source = add_budget(source, budget_text, **kwargs)
    source = add_tags(source, skills_rule)
    source = add_tags(source, categ_rule, assign='k:categories')
    source = clean_locations(source)
    source = remove_cruft(source)
    return source.output if stream else source


def parse_elance(source, stream=True):
    budget_text = 'Budget:</b>'
    fixed_text = 'Budget:</b> Fixed Price'
    hourly_text = 'Budget:</b> Hourly'

    no_job_loc = {'field': 'summary', 'text': 'Preferred Job Location'}
    no_client_loc = {'field': 'summary', 'text': 'Client Location'}
    no_budget = {'field': 'summary', 'text': budget_text}
    isnt_fixed = {'field': 'summary', 'text': fixed_text}
    isnt_hourly = {'field': 'summary', 'text': hourly_text}
    raw_budget_rule = [{'find': budget_text, 'location': 'after'}, BR]
    after_hourly = {'rule': {'find': 'Hourly', 'location': 'after'}}
    after_fixed = {'rule': {'find': 'Fixed Price', 'location': 'after'}}
    title_conf = {'rule': {'find': '| Elance Job'}}

    find_id_rule = [
        {'find': '/', 'param': 'last'},
        {'find': '/', 'location': 'after', 'param': 'last'}]

    categ_rule = [{'find': 'Category:</b>', 'location': 'after'}, BR]
    skills_rule = [{'find': 'Desired Skills:</b>', 'location': 'after'}, BR]

    job_loc_conf = {
        'rule': [
            {'find': 'Preferred Job Location:</b>', 'location': 'after'}, BR]}

    client_loc_conf = {
        'rule': [{'find': 'Client Location:</b>', 'location': 'after'}, BR]}

    desc_rule = [
        {'find': '<p>', 'location': 'after'}, {'find': '...\n    <br>'}]

    proposals_conf = {
        'rule': [
            {'find': 'Proposals:</b>', 'location': 'after'}, {'find': '('}]}

    jobs_posted_conf = {
        'rule': [
            {'find': 'Client:</b> Client (', 'location': 'after'},
            {'find': 'jobs posted'}]}

    jobs_awarded_conf = {
        'rule': [
            {'find': 'jobs posted,', 'location': 'after'},
            {'find': 'awarded'}]}

    purchased_conf = {
        'rule': [
            {'find': 'total purchased'},
            {'find': ',', 'location': 'after', 'param': 'last'}]}

    ends_conf = {
        'rule': [
            {'find': 'Time Left:</b>', 'location': 'after'},
            {'find': ') <br>'},
            {'find': 'h (Ends', 'location': 'after'}]}

    source = (source
        .strfind(conf=title_conf, field='title', assign='title')
        .strfind(conf=proposals_conf, field='summary', assign='k:submissions')
        .strfind(conf=jobs_posted_conf, field='summary', assign='k:num_jobs')
        .strfind(
            conf=jobs_awarded_conf, field='summary', assign='k:per_awarded')
        .strfind(conf=purchased_conf, field='summary', assign='k:tot_purchased')
        .strfind(conf=ends_conf, field='summary', assign='k:due')
        .strfind(
            conf=job_loc_conf, field='summary', assign='k:work_location',
            skip_if=no_job_loc)
        .strfind(
            conf=client_loc_conf, field='summary', assign='k:client_location',
            skip_if=no_client_loc)
        .strfind(
            conf={'rule': desc_rule}, field='summary', assign='description')
        .strfind(
            conf={'rule': raw_budget_rule}, field='summary',
            assign='k:budget_raw', skip_if=no_budget)
        .strfind(
            conf=after_hourly, field='k:budget_raw', assign='k:budget_raw',
            skip_if=isnt_hourly)
        .strfind(
            conf=after_fixed, field='k:budget_raw', assign='k:budget_raw',
            skip_if=isnt_fixed)
    )

    kwargs = {'fixed_text': fixed_text, 'hourly_text': hourly_text}
    source = add_source(source)
    source = add_posted(source)
    source = add_id(source, find_id_rule)
    source = add_budget(source, budget_text, **kwargs)
    source = add_tags(source, skills_rule)
    source = add_tags(source, categ_rule, assign='k:categories')
    source = clean_locations(source)
    source = remove_cruft(source)
    return source.output if stream else source


def parse_freelancer(source, stream=True):
    budget_text = '(Budget:'
    no_budget = {'field': 'summary', 'text': budget_text}
    raw_budget_rule = [
        {'find': budget_text, 'location': 'after'}, {'find': ','}]

    title_rule = {'find': ' by '}
    skills_rule = [{'find': ', Jobs:', 'location': 'after'}, {'find': ')</p>'}]
    desc_rule = [{'find': '<p>', 'location': 'after'}, {'find': '(Budget:'}]

    source = (source
        .strfind(conf={'rule': title_rule}, field='title', assign='title')
        .strfind(
            conf={'rule': desc_rule}, field='summary', assign='description')
        .strfind(
            conf={'rule': raw_budget_rule}, field='summary',
            assign='k:budget_raw', skip_if=no_budget)
    )

    source = add_source(source)
    source = add_posted(source)
    source = add_budget(source, budget_text)
    source = add_tags(source, skills_rule)
    source = clean_locations(source)
    source = remove_cruft(source)
    return source.output if stream else source


def pipe(test=False, parallel=False, threads=False):
    kwargs = {'parallel': parallel, 'threads': threads}

    Pipe = partial(SyncPipe, 'fetchdata', **kwargs)
    odesk_source = Pipe(conf=odesk_conf)
    guru_source = Pipe(conf=guru_conf)
    freelancer_source = Pipe(conf=freelancer_conf)
    elance_source = Pipe(conf=elance_conf)
    # odesk_source = SyncPipe('fetchdata', conf=odesk_conf, **kwargs)
    # guru_source = SyncPipe('fetchdata', conf=guru_conf, **kwargs)
    # elance_source = SyncPipe('fetchdata', conf=elance_conf, **kwargs)
    # freelancer_source = SyncPipe('fetchdata', conf=freelancer_conf, **kwargs)

    odesk_pipe = parse_odesk(odesk_source, stream=False)
    guru_stream = parse_guru(guru_source)
    elance_stream = parse_elance(elance_source)
    freelancer_stream = parse_freelancer(freelancer_source)

    others = [guru_stream, freelancer_stream, elance_stream]
    stream = odesk_pipe.union(others=others).list

    pprint(stream[-1])
    return stream


@coroutine
def async_pipe(reactor, test=None):
    Pipe = partial(AsyncPipe, 'fetchdata')
    odesk_source = Pipe(conf=odesk_conf)
    guru_source = Pipe(conf=guru_conf)
    freelancer_source = Pipe(conf=freelancer_conf)
    elance_source = Pipe(conf=elance_conf)

    odesk_pipe = yield parse_odesk(odesk_source, stream=False)
    guru_stream = yield parse_guru(guru_source)
    elance_stream = yield parse_elance(elance_source)
    freelancer_stream = yield parse_freelancer(freelancer_source)

    others = [guru_stream, freelancer_stream, elance_stream]
    stream = odesk_pipe.union(others=others).list
    pprint(stream[-1])
