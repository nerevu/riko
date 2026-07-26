# vim: sw=4:ts=4:expandtab

from functools import partial
from pprint import pprint
from typing import cast

from riko import get_path
from riko.collections import AsyncPipe, SyncPipe
from riko.types.general import Items
from riko.types.modules import (
    CurrencyFormatConf,
    CurrencyFormatRawConf,
    ExchangeRateConf,
    FetchDataConf,
    FindConfRule,
    RenameConf,
    RenameConfRule,
    SimpleMathRawConf,
    Skip,
    StrconcatConf,
    StrfindConf,
    StrReplaceConfRule,
    StrTransformConf,
    StrTransformConfRule,
    SubelementConf,
    Subkey,
)

# from riko.utils import make_regex_rule

BR = FindConfRule(find="<br>")
DEF_CUR_CODE = "USD"

odesk_conf = FetchDataConf({"url": get_path("odesk.json"), "path": "items"})
guru_conf = FetchDataConf({"url": get_path("guru.json"), "path": "items"})
elance_conf = FetchDataConf({"url": get_path("elance.json"), "path": "items"})
freelancer_conf = FetchDataConf({"url": get_path("freelancer.json"), "path": "items"})


def make_simplemath(other: str, op: str) -> SimpleMathRawConf:
    return SimpleMathRawConf(
        {
            "other": {"subkey": other, "type": "float"},
            "op": {"value": op, "type": "text"},
        }
    )


def add_source[T: SyncPipe | AsyncPipe](source: T) -> T:
    subelement_conf = SubelementConf({"path": "k:source.content.1", "token_key": None})

    result = source.urlparse(field="link", emit=False, assign="k:source").subelement(
        conf=subelement_conf, emit=False, assign="k:source"
    )
    return cast(T, result)


def add_id[T: SyncPipe | AsyncPipe](source: T, rule, field="link") -> T:
    make_id_part = [
        {"subkey": "k:source", "type": "text"},
        "-",
        {"subkey": "id", "type": "text"},
    ]

    result = source.strfind(conf={"rule": rule}, field=field, assign="id").strconcat(
        conf={"part": make_id_part}, assign="id"
    )
    return cast(T, result)


def add_posted[T: SyncPipe | AsyncPipe](
    source: T,
    rule: FindConfRule | list[FindConfRule] | None = None,
    field="summary",
) -> T:
    if rule:
        conf = StrfindConf({"rule": rule})
        result = source.strfind(conf=conf, field=field, assign="k:posted")
    else:
        rename_rule = RenameConfRule(field="updated", newval="k:posted")
        result = source.rename(conf={"rule": rename_rule})

    return cast(T, result)


def add_tags[T: SyncPipe | AsyncPipe](
    source: T, rule, field="summary", assign="k:tags"
) -> T:
    no_tags = Skip({"field": assign})

    tag_strreplace_rule = [
        StrReplaceConfRule(find="  ", replace=","),
        StrReplaceConfRule(find="&gt;", replace=","),
        StrReplaceConfRule(find="&amp;", replace="&"),
        StrReplaceConfRule(find="Other -", replace=""),
        # StrReplaceConfRule(find='-', replace=''),
    ]

    result = (
        source.strfind(conf={"rule": rule}, field=field, assign=assign)
        .strreplace(
            conf={"rule": tag_strreplace_rule},
            field=assign,
            assign=assign,
            skip_if=no_tags,
        )
        .strtransform(
            conf=StrTransformConf({"rule": StrTransformConfRule(transform="lower")}),
            field=assign,
            assign=assign,
            skip_if=no_tags,
        )
        .tokenizer(
            conf={"dedupe": True, "sort": True},
            field=assign,
            emit=False,
            assign=assign,
            skip_if=no_tags,
        )
    )
    return cast(T, result)


def add_budget[T: SyncPipe | AsyncPipe](
    source: T,
    fixed_text="",
    hourly_text="",
    double: bool | str = True,
) -> T:
    codes = "$£€₹"
    no_raw_budget = Skip({"field": "k:budget_raw"})
    has_code = Skip({"field": "k:cur_code", "include": True})
    is_def_cur = Skip({"field": "k:cur_code", "text": DEF_CUR_CODE})
    not_def_cur = Skip({"field": "k:cur_code", "text": DEF_CUR_CODE, "include": True})
    isnt_fixed = Skip({"field": "summary", "text": fixed_text, "include": True})
    isnt_hourly = Skip({"field": "summary", "text": hourly_text, "include": True})
    no_symbol = Skip(
        {
            "field": "k:budget_raw",
            "text": codes,
            "op": "intersection",
            "include": True,
        }
    )
    code_or_no_raw_budget = [has_code, no_raw_budget]
    def_cur_or_no_raw_budget = [is_def_cur, no_raw_budget]
    not_def_cur_or_no_raw_budget = [not_def_cur, no_raw_budget]

    first_num_rule = FindConfRule(find=r"\d+", location="at")
    last_num_rule = FindConfRule(find=r"\d+", location="at", param="last")
    cur_rule = FindConfRule(find=r"\b[A-Z]{3}\b", location="at")
    sym_rule = FindConfRule(find=f"[{codes}]", location="at")

    # make_regex_rule('k:budget_raw', r'[(),.\s]', ''),
    invalid_budgets = [
        StrReplaceConfRule(find="Less than", replace="0-"),
        StrReplaceConfRule(find="Under", replace="0-"),
        StrReplaceConfRule(find="Upto", replace="0-"),
        StrReplaceConfRule(find="or less", replace="-0"),
        StrReplaceConfRule(find="k", replace="000"),
        StrReplaceConfRule(find="Not Sure", replace=""),
        StrReplaceConfRule(find="Not sure", replace=""),
        StrReplaceConfRule(find="(", replace=""),
        StrReplaceConfRule(find=")", replace=""),
        StrReplaceConfRule(find=".", replace=""),
        StrReplaceConfRule(find=",", replace=""),
        StrReplaceConfRule(find=" ", replace=""),
    ]

    cur_strreplace_rule = [
        StrReplaceConfRule(find="$", replace="USD"),
        StrReplaceConfRule(find="£", replace="GBP"),
        StrReplaceConfRule(find="€", replace="EUR"),
        StrReplaceConfRule(find="₹", replace="INR"),
    ]

    converted_budget_part: list[str | Subkey] = [
        Subkey({"subkey": "k:budget_w_sym", "type": "text"}),
        "(",
        Subkey({"subkey": "k:budget_converted_w_sym", "type": "text"}),
        ")",
    ]

    def_full_budget_part = Subkey({"subkey": "k:budget_w_sym", "type": "text"})
    hourly_budget_part: list[str | Subkey] = [
        {"subkey": "k:budget_full", "type": "text"},
        " / hr",
    ]
    exchangerate_conf = ExchangeRateConf({"url": get_path("quote.json")})
    native_currencyformat_conf = CurrencyFormatRawConf(
        {"currency": {"subkey": "k:cur_code", "type": "text"}}
    )
    def_currencyformat_conf = CurrencyFormatConf({"currency": DEF_CUR_CODE})
    ave_budget_conf = make_simplemath("k:budget_raw2_num", "mean")
    convert_budget_conf = make_simplemath("k:rate", "multiply")

    if fixed_text:
        result = source.strconcat(
            conf={"part": "fixed"}, assign="k:job_type", skip_if=isnt_fixed
        )
    else:
        result = source

    if hourly_text:
        result = result.strconcat(
            conf={"part": "hourly"}, assign="k:job_type", skip_if=isnt_hourly
        )

    result = result.refind(
        conf={"rule": cur_rule},
        field="k:budget_raw",
        assign="k:cur_code",
        skip_if=no_raw_budget,
    ).strreplace(
        conf={"rule": invalid_budgets},
        field="k:budget_raw",
        assign="k:budget_raw",
        skip_if=no_raw_budget,
    )

    if double:
        result = (
            result.refind(
                conf={"rule": first_num_rule},
                field="k:budget_raw",
                assign="k:budget_raw_num",
                skip_if=no_raw_budget,
            )
            .refind(
                conf={"rule": last_num_rule},
                field="k:budget_raw",
                assign="k:budget_raw2_num",
                skip_if=no_raw_budget,
            )
            .simplemath(
                conf=ave_budget_conf,
                field="k:budget_raw_num",
                assign="k:budget",
                skip_if=no_raw_budget,
            )
        )
    else:
        result = result.refind(
            conf={"rule": first_num_rule},
            field="k:budget_raw",
            assign="k:budget",
            skip_if=no_raw_budget,
        )

    result = (
        result.refind(
            conf={"rule": sym_rule},
            field="k:budget_raw",
            assign="k:budget_raw_sym",
            skip_if=no_symbol,
        )
        .strreplace(
            conf={"rule": cur_strreplace_rule},
            field="k:budget_raw_sym",
            assign="k:cur_code",
            skip_if=code_or_no_raw_budget,
        )
        .currencyformat(
            conf=native_currencyformat_conf,
            field="k:budget",
            assign="k:budget_w_sym",
            skip_if=no_raw_budget,
        )
        .exchangerate(
            conf=exchangerate_conf,
            field="k:cur_code",
            assign="k:rate",
            skip_if=def_cur_or_no_raw_budget,
        )
        .simplemath(
            conf=convert_budget_conf,
            field="k:budget",
            assign="k:budget_converted",
            skip_if=def_cur_or_no_raw_budget,
        )
        .currencyformat(
            conf=def_currencyformat_conf,
            field="k:budget_converted",
            assign="k:budget_converted_w_sym",
            skip_if=def_cur_or_no_raw_budget,
        )
        .strconcat(
            conf=StrconcatConf({"part": converted_budget_part}),
            assign="k:budget_full",
            skip_if=def_cur_or_no_raw_budget,
        )
        .strconcat(
            conf=StrconcatConf({"part": def_full_budget_part}),
            assign="k:budget_full",
            skip_if=not_def_cur_or_no_raw_budget,
        )
    )

    if hourly_text:
        result = result.strconcat(
            conf={"part": hourly_budget_part},
            assign="k:budget_full",
            skip_if=isnt_hourly,
        )

    return cast(T, result)


def clean_locations[T: SyncPipe | AsyncPipe](source: T) -> T:
    no_client_loc = Skip({"field": "k:client_location"})
    no_work_loc = Skip({"field": "k:work_location"})
    rule = StrReplaceConfRule(find=", ", replace="")

    result = source.strreplace(
        conf={"rule": rule},
        field="k:client_location",
        assign="k:client_location",
        skip_if=no_client_loc,
    ).strreplace(
        conf={"rule": rule},
        field="k:work_location",
        assign="k:work_location",
        skip_if=no_work_loc,
    )

    return cast(T, result)


def remove_cruft[T: SyncPipe | AsyncPipe](source: T) -> T:
    remove_rule = [
        RenameConfRule(field="author"),
        RenameConfRule(field="content"),
        RenameConfRule(field="dc:creator"),
        RenameConfRule(field="links"),
        RenameConfRule(field="pubDate"),
        RenameConfRule(field="summary"),
        RenameConfRule(field="updated"),
        RenameConfRule(field="updated_parsed"),
        RenameConfRule(field="y:id"),
        RenameConfRule(field="y:title"),
        RenameConfRule(field="y:published"),
        RenameConfRule(field="k:budget_raw"),
        RenameConfRule(field="k:budget_raw2_num"),
        RenameConfRule(field="k:budget_raw_num"),
        RenameConfRule(field="k:budget_raw_sym"),
    ]

    result = source.rename(conf=RenameConf({"rule": remove_rule}))
    return cast(T, result)


def parse_odesk[T: SyncPipe | AsyncPipe](source: T) -> T:
    budget_text = "Budget</b>:"
    no_budget = Skip({"field": "summary", "text": budget_text, "include": True})
    raw_budget_rule = [FindConfRule(find=budget_text, location="after"), BR]
    title_rule = FindConfRule(find="- oDesk")
    find_id_rule = [FindConfRule(find="ID</b>:", location="after"), BR]
    categ_rule = [FindConfRule(find="Category</b>:", location="after"), BR]
    skills_rule = [FindConfRule(find="Skills</b>:", location="after"), BR]
    client_loc_rule = [FindConfRule(find="Country</b>:", location="after"), BR]
    posted_rule = [FindConfRule(find="Posted On</b>:", location="after"), BR]
    desc_rule = [
        FindConfRule(find="<p>", location="after"),
        FindConfRule(find="<br><br><b>"),
    ]

    result = (
        source.strfind(conf={"rule": title_rule}, field="title", assign="title")
        .strfind(
            conf={"rule": client_loc_rule}, field="summary", assign="k:client_location"
        )
        .strfind(conf={"rule": desc_rule}, field="summary", assign="description")
        .strfind(
            conf={"rule": raw_budget_rule},
            field="summary",
            assign="k:budget_raw",
            skip_if=no_budget,
        )
    )
    result = add_source(result)
    result = add_posted(result, posted_rule)
    result = add_id(result, find_id_rule, field="summary")
    result = add_budget(result, double=False)
    result = add_tags(result, skills_rule)
    result = add_tags(result, categ_rule, assign="k:categories")
    result = clean_locations(result)
    result = remove_cruft(result)
    return cast(T, result)


def parse_guru[T: SyncPipe | AsyncPipe](source: T) -> T:
    budget_text = "budget:</b>"
    fixed_text = "Fixed Price budget:</b>"
    hourly_text = "Hourly budget:</b>"

    no_budget = Skip({"field": "summary", "text": budget_text, "include": True})
    isnt_hourly = Skip({"field": "summary", "text": hourly_text, "include": True})
    raw_budget_rule = [FindConfRule(find=budget_text, location="after"), BR]
    after_hourly = StrfindConf({"rule": FindConfRule(find="Rate:", location="after")})
    find_id_rule = FindConfRule(find="/", location="after", param="last")
    categ_rule = [FindConfRule(find="Category:</b>", location="after"), BR]
    skills_rule = [FindConfRule(find="Required skills:</b>", location="after"), BR]

    job_loc_conf = StrfindConf(
        {"rule": [FindConfRule(find="Freelancer Location:</b>", location="after"), BR]}
    )

    desc_conf = StrfindConf(
        {"rule": [FindConfRule(find="Description:</b>", location="after"), BR]}
    )

    result = (
        source.strfind(conf=job_loc_conf, field="summary", assign="k:work_location")
        .strfind(conf=desc_conf, field="summary", assign="description")
        .strfind(
            conf={"rule": raw_budget_rule},
            field="summary",
            assign="k:budget_raw",
            skip_if=no_budget,
        )
        .strfind(
            conf=after_hourly,
            field="k:budget_raw",
            assign="k:budget_raw",
            skip_if=isnt_hourly,
        )
    )

    kwargs = {"fixed_text": fixed_text, "hourly_text": hourly_text}
    result = add_source(result)
    result = add_posted(result)
    result = add_id(result, find_id_rule)
    result = add_budget(result, **kwargs)
    result = add_tags(result, skills_rule)
    result = add_tags(result, categ_rule, assign="k:categories")
    result = clean_locations(result)
    result = remove_cruft(result)
    return cast(T, result)


def parse_elance[T: SyncPipe | AsyncPipe](source: T) -> T:
    budget_text = "Budget:</b>"
    fixed_text = "Budget:</b> Fixed Price"
    hourly_text = "Budget:</b> Hourly"

    no_job_loc = Skip(
        {"field": "summary", "text": "Preferred Job Location", "include": True}
    )
    no_client_loc = Skip(
        {"field": "summary", "text": "Client Location", "include": True}
    )
    no_budget = Skip({"field": "summary", "text": budget_text, "include": True})
    isnt_fixed = Skip({"field": "summary", "text": fixed_text, "include": True})
    isnt_hourly = Skip({"field": "summary", "text": hourly_text, "include": True})
    raw_budget_rule = [FindConfRule(find=budget_text, location="after"), BR]
    after_hourly = StrfindConf({"rule": FindConfRule(find="Hourly", location="after")})
    after_fixed = StrfindConf(
        {"rule": FindConfRule(find="Fixed Price", location="after")}
    )
    title_conf = StrfindConf({"rule": FindConfRule(find="| Elance Job")})

    find_id_rule = [
        FindConfRule(find="/", param="last"),
        FindConfRule(find="/", location="after", param="last"),
    ]

    categ_rule = [FindConfRule(find="Category:</b>", location="after"), BR]
    skills_rule = [FindConfRule(find="Desired Skills:</b>", location="after"), BR]

    job_loc_conf = StrfindConf(
        {
            "rule": [
                FindConfRule(find="Preferred Job Location:</b>", location="after"),
                BR,
            ]
        }
    )

    client_loc_conf = StrfindConf(
        {"rule": [FindConfRule(find="Client Location:</b>", location="after"), BR]}
    )

    desc_rule = [
        FindConfRule(find="<p>", location="after"),
        FindConfRule(find="...\n    <br>"),
    ]

    proposals_conf = StrfindConf(
        {
            "rule": [
                FindConfRule(find="Proposals:</b>", location="after"),
                FindConfRule(find="("),
            ]
        }
    )

    jobs_posted_conf = StrfindConf(
        {
            "rule": [
                FindConfRule(find="Client:</b> Client (", location="after"),
                FindConfRule(find="jobs posted"),
            ]
        }
    )

    jobs_awarded_conf = StrfindConf(
        {
            "rule": [
                FindConfRule(find="jobs posted,", location="after"),
                FindConfRule(find="awarded"),
            ]
        }
    )

    purchased_conf = StrfindConf(
        {
            "rule": [
                FindConfRule(find="total purchased"),
                FindConfRule(find=",", location="after", param="last"),
            ]
        }
    )

    ends_conf = StrfindConf(
        {
            "rule": [
                FindConfRule(find="Time Left:</b>", location="after"),
                FindConfRule(find=") <br>"),
                FindConfRule(find="h (Ends", location="after"),
            ]
        }
    )

    result = (
        source.strfind(conf=title_conf, field="title", assign="title")
        .strfind(conf=proposals_conf, field="summary", assign="k:submissions")
        .strfind(conf=jobs_posted_conf, field="summary", assign="k:num_jobs")
        .strfind(conf=jobs_awarded_conf, field="summary", assign="k:per_awarded")
        .strfind(conf=purchased_conf, field="summary", assign="k:tot_purchased")
        .strfind(conf=ends_conf, field="summary", assign="k:due")
        .strfind(
            conf=job_loc_conf,
            field="summary",
            assign="k:work_location",
            skip_if=no_job_loc,
        )
        .strfind(
            conf=client_loc_conf,
            field="summary",
            assign="k:client_location",
            skip_if=no_client_loc,
        )
        .strfind(conf={"rule": desc_rule}, field="summary", assign="description")
        .strfind(
            conf={"rule": raw_budget_rule},
            field="summary",
            assign="k:budget_raw",
            skip_if=no_budget,
        )
        .strfind(
            conf=after_hourly,
            field="k:budget_raw",
            assign="k:budget_raw",
            skip_if=isnt_hourly,
        )
        .strfind(
            conf=after_fixed,
            field="k:budget_raw",
            assign="k:budget_raw",
            skip_if=isnt_fixed,
        )
    )

    kwargs = {"fixed_text": fixed_text, "hourly_text": hourly_text}
    result = add_source(result)
    result = add_posted(result)
    result = add_id(result, find_id_rule)
    result = add_budget(result, **kwargs)
    result = add_tags(result, skills_rule)
    result = add_tags(result, categ_rule, assign="k:categories")
    result = clean_locations(result)
    # result = remove_cruft(result)
    return cast(T, result)


def parse_freelancer[T: SyncPipe | AsyncPipe](source: T) -> T:
    budget_text = "(Budget:"
    no_budget = Skip({"field": "summary", "text": budget_text, "include": True})
    raw_budget_rule = [
        FindConfRule(find=budget_text, location="after"),
        FindConfRule(find=","),
    ]

    title_rule = FindConfRule(find=" by ")
    skills_rule = [
        FindConfRule(find=", Jobs:", location="after"),
        FindConfRule(find=")</p>"),
    ]
    desc_rule = [
        FindConfRule(find="<p>", location="after"),
        FindConfRule(find="(Budget:"),
    ]

    result = (
        source.strfind(conf={"rule": title_rule}, field="title", assign="title")
        .strfind(conf={"rule": desc_rule}, field="summary", assign="description")
        .strfind(
            conf={"rule": raw_budget_rule},
            field="summary",
            assign="k:budget_raw",
            skip_if=no_budget,
        )
    )

    result = add_source(result)
    result = add_posted(result)
    result = add_budget(result)
    result = add_tags(result, skills_rule)
    result = clean_locations(result)
    result = remove_cruft(result)
    return cast(T, result)


def pipe(test=False, parallel=False, threads=False) -> Items:
    kwargs = {"parallel": parallel, "threads": threads}

    pipe = partial(SyncPipe, "fetchdata", **kwargs)
    odesk_source = pipe(conf=odesk_conf)
    guru_source = pipe(conf=guru_conf)
    freelancer_source = pipe(conf=freelancer_conf)
    elance_source = pipe(conf=elance_conf)

    odesk_pipe = parse_odesk(odesk_source)  # 10
    guru_stream = parse_guru(guru_source)  # 75
    freelancer_stream = parse_freelancer(freelancer_source)  # 20
    elance_stream = parse_elance(elance_source)  # 75

    others = [guru_stream, freelancer_stream, elance_stream]
    return list(odesk_pipe.union(others=others))


async def async_pipe(test=None) -> Items:
    pipe = partial(AsyncPipe, "fetchdata")
    odesk_source = pipe(conf=odesk_conf)
    guru_source = pipe(conf=guru_conf)
    freelancer_source = pipe(conf=freelancer_conf)
    elance_source = pipe(conf=elance_conf)

    odesk_pipe = await parse_odesk(odesk_source)
    guru_stream = await parse_guru(guru_source)
    elance_stream = await parse_elance(elance_source)
    freelancer_stream = await parse_freelancer(freelancer_source)

    others = [guru_stream, freelancer_stream, elance_stream]
    stream = await cast(AsyncPipe, odesk_pipe).union(others=others)
    return list(stream)


def print_results(result) -> None:
    pprint(result[-1])


def main(*, test: bool = False) -> None:
    print_results(pipe(test=test))


if __name__ == "__main__":
    main()
