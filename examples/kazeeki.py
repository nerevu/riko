# vim: sw=4:ts=4:expandtab

"""
Aggregate freelance jobs from several feeds and normalize their budgets.

The feeds are odesk, guru, elance, and freelancer.

Examples:

    Run it::

        run-pipe kazeeki

"""

from __future__ import annotations

from itertools import chain
from pprint import pprint
from typing import TYPE_CHECKING

from riko import Pipeline, async_chain, get_path
from riko.types import CallOptions
from riko.types.modules import (
    CurrencyFormatConf,
    CurrencyFormatRawConf,
    ExchangeRateConf,
    FetchDataConf,
    FindConfRule,
    RenameConf,
    RenameConfRule,
    SimpleMathRawConf,
    StrconcatConf,
    StrfindConf,
    StrReplaceConfRule,
    StrTransformConf,
    StrTransformConfRule,
    SubelementConf,
    Subkey,
)

if TYPE_CHECKING:
    from typing import Literal

    from riko.types import AsyncStream, Item

type Rules = FindConfRule | list[FindConfRule]

DEF_CUR_CODE = "USD"


def find_rule(
    find: str,
    location: Literal["before", "after", "at"] = "before",
    param: Literal["first", "last"] = "first",
) -> FindConfRule:
    return FindConfRule(find=find, location=location, param=param)


def until_br(find: str) -> list[FindConfRule]:
    return [find_rule(find, "after"), find_rule("<br>")]


def between(start: str, end: str) -> list[FindConfRule]:
    return [find_rule(start, "after"), find_rule(end)]


def text_subkey(subkey: str) -> Subkey:
    return Subkey({"subkey": subkey, "type": "text"})


def same_field(field: str) -> CallOptions:
    return CallOptions(field=field, assign=field)


def from_summary(assign: str) -> CallOptions:
    return CallOptions(field="summary", assign=assign)


def build_replace_rules(replacements: dict[str, str]) -> list[StrReplaceConfRule]:
    items = replacements.items()
    return [StrReplaceConfRule(find=find, replace=replace) for find, replace in items]


def build_fetchdata(name: str) -> Pipeline:
    conf = FetchDataConf({"url": get_path(f"{name}.json"), "path": "items"})
    return Pipeline.from_module("fetchdata", conf=conf)


def build_simplemath(other: str, op: str) -> SimpleMathRawConf:
    return SimpleMathRawConf(
        {
            "other": {"subkey": other, "type": "float"},
            "op": {"value": op, "type": "text"},
        }
    )


def add_source(source: Pipeline) -> Pipeline:
    subelement_conf = SubelementConf({"path": "k:source.content.1", "token_key": None})
    urlparse_options = CallOptions(field="link", emit=False, assign="k:source")
    subelement_options = CallOptions(emit=False, assign="k:source", count="first")
    parsed = source.urlparse(options=urlparse_options)
    return parsed.subelement(conf=subelement_conf, options=subelement_options)


def add_id(source: Pipeline, rule: Rules, field: str = "link") -> Pipeline:
    id_part = [text_subkey("k:source"), "-", text_subkey("id")]
    found = source.strfind(
        conf={"rule": rule}, options={"field": field, "assign": "id"}
    )
    return found.strconcat(conf={"part": id_part}, options={"assign": "id"})


def add_posted(
    source: Pipeline, rule: Rules | None = None, field: str = "summary"
) -> Pipeline:
    if rule is None:
        rename_rule = RenameConfRule(field="updated", newval="k:posted")
        result = source.rename(conf={"rule": rename_rule})
    else:
        conf = StrfindConf({"rule": rule})
        strfind_opts = {"field": field, "assign": "k:posted"}
        result = source.strfind(conf=conf, options=strfind_opts)

    return result


def add_tags(
    source: Pipeline, rule: Rules, field: str = "summary", assign: str = "k:tags"
) -> Pipeline:
    tag_strreplace_rule = build_replace_rules(
        {"  ": ",", "&gt;": ",", "&amp;": "&", "Other -": ""}
    )

    transform_conf = StrTransformConf({"rule": StrTransformConfRule(transform="lower")})
    in_place = same_field(assign)

    return (
        source.strfind(conf={"rule": rule}, options={"field": field, "assign": assign})
        .strreplace(conf={"rule": tag_strreplace_rule}, options=in_place)
        .strtransform(conf=transform_conf, options=in_place)
        .tokenizer(
            conf={"dedupe": True, "sort": True},
            options={"field": assign, "emit": False, "assign": assign},
        )
    )


def add_categories(source: Pipeline, rule: Rules) -> Pipeline:
    return add_tags(source, rule, assign="k:categories")


def add_budget(
    source: Pipeline, fixed: bool = False, hourly: bool = False, double: bool = True
) -> Pipeline:
    marked, codes = source, "$£€₹"
    first_num_rule = find_rule(r"\d+", "at")
    last_num_rule = find_rule(r"\d+", "at", "last")
    cur_rule = find_rule(r"\b[A-Z]{3}\b", "at")
    sym_rule = find_rule(f"[{codes}]", "at")

    invalid_budgets = build_replace_rules(
        {
            "Less than": "0-",
            "Under": "0-",
            "Upto": "0-",
            "or less": "-0",
            "k": "000",
            "Not Sure": "",
            "Not sure": "",
            "(": "",
            ")": "",
            ".": "",
            ",": "",
            " ": "",
        }
    )

    cur_strreplace_rule = build_replace_rules(
        {"$": "USD", "£": "GBP", "€": "EUR", "₹": "INR"}
    )

    budget_w_sym = text_subkey("k:budget_w_sym")
    _subkey = text_subkey("k:budget_converted_w_sym")
    converted_budget_part = [budget_w_sym, "(", _subkey, ")"]
    hourly_budget_part = [text_subkey("k:budget_full"), " / hr"]
    exchangerate_conf = ExchangeRateConf({"url": get_path("quote.json")})
    native_currencyformat_conf = CurrencyFormatRawConf(
        {"currency": text_subkey("k:cur_code")}
    )
    def_currencyformat_conf = CurrencyFormatConf({"currency": DEF_CUR_CODE})
    ave_budget_conf = build_simplemath("k:budget_raw2_num", "mean")
    convert_budget_conf = build_simplemath("k:rate", "multiply")
    raw_budget = same_field("k:budget_raw")
    _job_type = {"assign": "k:job_type"}

    if fixed:
        marked = source.strconcat(conf={"part": "fixed"}, options=_job_type)

    if hourly:
        typed = marked.strconcat(conf={"part": "hourly"}, options=_job_type)
    else:
        typed = marked

    cleaned = typed.refind(
        conf={"rule": cur_rule},
        options={"field": "k:budget_raw", "assign": "k:cur_code"},
    ).strreplace(conf={"rule": invalid_budgets}, options=raw_budget)

    if double:
        amounted = (
            cleaned.refind(
                conf={"rule": first_num_rule},
                options={"field": "k:budget_raw", "assign": "k:budget_raw_num"},
            )
            .refind(
                conf={"rule": last_num_rule},
                options={"field": "k:budget_raw", "assign": "k:budget_raw2_num"},
            )
            .simplemath(
                conf=ave_budget_conf,
                options={"field": "k:budget_raw_num", "assign": "k:budget"},
            )
        )
    else:
        amounted = cleaned.refind(
            conf={"rule": first_num_rule},
            options={"field": "k:budget_raw", "assign": "k:budget"},
        )

    _budget_full = {"assign": "k:budget_full"}

    formatted = (
        amounted.refind(
            conf={"rule": sym_rule},
            options={"field": "k:budget_raw", "assign": "k:budget_raw_sym"},
        )
        .strreplace(
            conf={"rule": cur_strreplace_rule},
            options={"field": "k:budget_raw_sym", "assign": "k:cur_code"},
        )
        .currencyformat(
            conf=native_currencyformat_conf,
            options={"field": "k:budget", "assign": "k:budget_w_sym"},
        )
        .exchangerate(
            conf=exchangerate_conf, options={"field": "k:cur_code", "assign": "k:rate"}
        )
        .simplemath(
            conf=convert_budget_conf,
            options={"field": "k:budget", "assign": "k:budget_converted"},
        )
        .currencyformat(
            conf=def_currencyformat_conf,
            options={
                "field": "k:budget_converted",
                "assign": "k:budget_converted_w_sym",
            },
        )
        .strconcat(
            conf=StrconcatConf({"part": converted_budget_part}), options=_budget_full
        )
        .strconcat(conf=StrconcatConf({"part": budget_w_sym}), options=_budget_full)
    )

    if hourly:
        budgeted = formatted.strconcat(
            conf={"part": hourly_budget_part}, options=_budget_full
        )
    else:
        budgeted = formatted

    return budgeted


def clean_locations(source: Pipeline) -> Pipeline:
    rule = StrReplaceConfRule(find=", ", replace="")
    client = same_field("k:client_location")
    work = same_field("k:work_location")
    replaced = source.strreplace(conf={"rule": rule}, options=client)
    return replaced.strreplace(conf={"rule": rule}, options=work)


def extract_title(source: Pipeline, rule: Rules) -> Pipeline:
    return source.strfind(conf={"rule": rule}, options=same_field("title"))


def remove_cruft(source: Pipeline) -> Pipeline:
    cruft = (
        "author",
        "content",
        "dc:creator",
        "links",
        "pubDate",
        "summary",
        "updated",
        "updated_parsed",
        "y:id",
        "y:title",
        "y:published",
        "k:budget_raw",
        "k:budget_raw2_num",
        "k:budget_raw_num",
        "k:budget_raw_sym",
    )
    remove_rule = [RenameConfRule(field=field) for field in cruft]
    return source.rename(conf=RenameConf({"rule": remove_rule}))


def parse_odesk(source: Pipeline) -> Pipeline:
    raw_budget_rule = until_br("Budget</b>:")
    title_rule = find_rule("- oDesk")
    find_id_rule = until_br("ID</b>:")
    categ_rule = until_br("Category</b>:")
    skills_rule = until_br("Skills</b>:")
    client_loc_rule = until_br("Country</b>:")
    posted_rule = until_br("Posted On</b>:")
    desc_rule = between("<p>", "<br><br><b>")
    titled = extract_title(source, title_rule)

    extracted = (
        titled.strfind(
            conf={"rule": client_loc_rule}, options=from_summary("k:client_location")
        )
        .strfind(conf={"rule": desc_rule}, options=from_summary("description"))
        .strfind(conf={"rule": raw_budget_rule}, options=from_summary("k:budget_raw"))
    )

    sourced = add_source(extracted)
    posted = add_posted(sourced, posted_rule)
    identified = add_id(posted, find_id_rule, field="summary")
    budgeted = add_budget(identified, double=False)
    tagged = add_tags(budgeted, skills_rule)
    categorized = add_categories(tagged, categ_rule)
    located = clean_locations(categorized)
    return remove_cruft(located)


def parse_guru(source: Pipeline) -> Pipeline:
    raw_budget_rule = until_br("budget:</b>")
    after_hourly_rule = find_rule("Rate:", "after")
    find_id_rule = find_rule("/", "after", "last")
    categ_rule = until_br("Category:</b>")
    skills_rule = until_br("Required skills:</b>")
    job_loc_rule = until_br("Freelancer Location:</b>")
    desc_rule = until_br("Description:</b>")

    extracted = (
        source.strfind(
            conf={"rule": job_loc_rule}, options=from_summary("k:work_location")
        )
        .strfind(conf={"rule": desc_rule}, options=from_summary("description"))
        .strfind(conf={"rule": raw_budget_rule}, options=from_summary("k:budget_raw"))
        .strfind(conf={"rule": after_hourly_rule}, options=same_field("k:budget_raw"))
    )

    sourced = add_source(extracted)
    posted = add_posted(sourced)
    identified = add_id(posted, find_id_rule)
    budgeted = add_budget(identified, fixed=True, hourly=True)
    tagged = add_tags(budgeted, skills_rule)
    categorized = add_categories(tagged, categ_rule)
    located = clean_locations(categorized)
    return remove_cruft(located)


def parse_elance(source: Pipeline) -> Pipeline:
    raw_budget_rule = until_br("Budget:</b>")
    after_hourly_rule = find_rule("Hourly", "after")
    after_fixed_rule = find_rule("Fixed Price", "after")
    title_rule = find_rule("| Elance Job")
    find_id_rule = [find_rule("/", param="last"), find_rule("/", "after", "last")]
    categ_rule = until_br("Category:</b>")
    skills_rule = until_br("Desired Skills:</b>")
    job_loc_rule = until_br("Preferred Job Location:</b>")
    client_loc_rule = until_br("Client Location:</b>")
    desc_rule = between("<p>", "...\n    <br>")
    proposals_rule = between("Proposals:</b>", "(")
    jobs_posted_rule = between("Client:</b> Client (", "jobs posted")
    jobs_awarded_rule = between("jobs posted,", "awarded")
    purchased_rule = [find_rule("total purchased"), find_rule(",", "after", "last")]
    ends_rule = [
        find_rule("Time Left:</b>", "after"),
        find_rule(") <br>"),
        find_rule("h (Ends", "after"),
    ]

    titled = extract_title(source, title_rule)
    extracted = (
        titled.strfind(
            conf={"rule": proposals_rule}, options=from_summary("k:submissions")
        )
        .strfind(conf={"rule": jobs_posted_rule}, options=from_summary("k:num_jobs"))
        .strfind(
            conf={"rule": jobs_awarded_rule}, options=from_summary("k:per_awarded")
        )
        .strfind(conf={"rule": purchased_rule}, options=from_summary("k:tot_purchased"))
        .strfind(conf={"rule": ends_rule}, options=from_summary("k:due"))
        .strfind(conf={"rule": job_loc_rule}, options=from_summary("k:work_location"))
        .strfind(
            conf={"rule": client_loc_rule}, options=from_summary("k:client_location")
        )
        .strfind(conf={"rule": desc_rule}, options=from_summary("description"))
        .strfind(conf={"rule": raw_budget_rule}, options=from_summary("k:budget_raw"))
        .strfind(conf={"rule": after_hourly_rule}, options=same_field("k:budget_raw"))
        .strfind(conf={"rule": after_fixed_rule}, options=same_field("k:budget_raw"))
    )

    sourced = add_source(extracted)
    posted = add_posted(sourced)
    identified = add_id(posted, find_id_rule)
    budgeted = add_budget(identified, fixed=True, hourly=True)
    tagged = add_tags(budgeted, skills_rule)
    categorized = add_categories(tagged, categ_rule)
    return clean_locations(categorized)


def parse_freelancer(source: Pipeline) -> Pipeline:
    raw_budget_rule = between("(Budget:", ",")
    title_rule = find_rule(" by ")
    skills_rule = between(", Jobs:", ")</p>")
    desc_rule = between("<p>", "(Budget:")
    titled = extract_title(source, title_rule)

    extracted = titled.strfind(
        conf={"rule": desc_rule}, options=from_summary("description")
    ).strfind(conf={"rule": raw_budget_rule}, options=from_summary("k:budget_raw"))

    sourced = add_source(extracted)
    posted = add_posted(sourced)
    budgeted = add_budget(posted)
    tagged = add_tags(budgeted, skills_rule)
    located = clean_locations(tagged)
    return remove_cruft(located)


def build_pipelines() -> list[Pipeline]:
    return [
        parse_odesk(build_fetchdata("odesk")),
        parse_guru(build_fetchdata("guru")),
        parse_freelancer(build_fetchdata("freelancer")),
        parse_elance(build_fetchdata("elance")),
    ]


def pipe(test: bool = False) -> list[Item]:
    return list(chain.from_iterable(build_pipelines()))


def async_pipe(test: bool = False) -> AsyncStream:
    return async_chain(*build_pipelines())


def print_results(result: list[Item]) -> None:
    pprint(result[-1])


def main(*, test: bool = False) -> None:
    print_results(pipe(test=test))


if __name__ == "__main__":
    main()
