# vim: sw=4:ts=4:expandtab

from pprint import pprint

from riko._strutils import make_regex_rule
from riko.collections import SyncPipe
from riko.context import Context
from riko.paths import get_path
from riko.types.general import SkipIf
from riko.types.modules import (
    CurrencyFormatConf,
    CurrencyFormatRawConf,
    ExchangeRateConf,
    FetchConf,
    FetchDataConf,
    RegexConf,
    RegexConfRule,
    RenameConf,
    RenameConfRule,
    SimpleMathRawConf,
    StrconcatConf,
    StrReplaceConf,
    StrReplaceConfRule,
    SubstrConf,
    TokenizerConf,
)

DEF_CUR_CODE = "USD"


def make_simplemath(other: str, op: str) -> SimpleMathRawConf:
    return SimpleMathRawConf(
        {
            "other": {"subkey": other, "type": "float"},
            "op": {"value": op, "type": "text"},
        }
    )


def make_substring(start: str | int, length: str | int) -> SubstrConf:
    return SubstrConf({"start": int(start), "length": int(length)})


def make_exchangerate(quote: str = DEF_CUR_CODE) -> ExchangeRateConf:
    return ExchangeRateConf({"currency": quote})


def make_tokenizer(delimiter: str, dedupe=False, sort=False) -> TokenizerConf:
    return TokenizerConf({"delimiter": delimiter, "dedupe": dedupe, "sort": sort})


rename1_rule = [
    RenameConfRule(newval="", field="y:title", copy=False),
    RenameConfRule(newval="", field="content", copy=False),
    RenameConfRule(newval="k:posted", field="y:published", copy=False),
    RenameConfRule(newval="k:job_type", field="summary", copy=True),
    RenameConfRule(newval="k:content", field="summary", copy=True),
    RenameConfRule(newval="k:work_location", field="summary", copy=True),
    RenameConfRule(newval="k:client_location", field="summary", copy=True),
    # RenameConfRule(newval="k:category", field="summary", copy=True),
    RenameConfRule(newval="k:tags", field="summary", copy=True),
    RenameConfRule(newval="k:due", field="summary", copy=True),
    RenameConfRule(newval="k:submissions", field="summary", copy=True),
    RenameConfRule(newval="k:budget_raw", field="summary", copy=True),
    RenameConfRule(newval="k:marketplace", field="link", copy=True),
    RenameConfRule(newval="k:author", field="title", copy=True),
]

rename2_rule = [
    RenameConfRule(newval="k:budget_raw1", field="k:budget_raw", copy=True),
    RenameConfRule(newval="k:budget_raw2", field="k:budget_raw", copy=True),
]

rename3_rule = [
    RenameConfRule(newval="k:budget_raw1_num", field="k:budget_raw1", copy=True),
    RenameConfRule(newval="k:budget_raw1_sym", field="k:budget_raw1", copy=True),
    RenameConfRule(newval="k:budget_raw1_code", field="k:budget_raw1", copy=True),
    RenameConfRule(newval="k:budget_raw2_num", field="k:budget_raw2", copy=True),
    RenameConfRule(newval="k:budget_raw2_sym", field="k:budget_raw2", copy=True),
    RenameConfRule(newval="k:budget_raw2_code", field="k:budget_raw2", copy=True),
]

rename4_rule = RenameConfRule(newval="k:budget_full", field="k:budget_w_sym", copy=True)

match1_01 = "(.*)( - oDesk|\\| Elance Job)"
match1_02 = (
    "^(http[s]?:\\/\\/)?\\/?([^\\/\\.]+\\.)*([^\\/\\.]+\\.[^:\\/\\s\\.]{2,3})(.*)"
)
match1_03 = ".*(Hourly budget:|Budget:<.*?> Hourly).*"
match1_04 = ".*(Fixed Price budget:|Budget:<.*?> Fixed Price).*"
match1_05 = "^(?!\\b(hourly|fixed)\\b).*"
match1_06 = "(.*)(<b>)?(Category|Budget):?(<.*?>)?(.*)"
match1_07 = "(.*)(<b>Description:<.*?>)(.*?)(<.*?>)(.*)"
match1_08 = "(.*)(<b>Proposals:<.*?>)(.*?)(<a href)(.*)"
match1_09 = "(.*)(<b>)(.*)"
match1_10 = "(.*)(\\bby\\b)(.*)"
match1_11 = "(.*)(<b>)(.*)"
match1_12 = "(.*)(<b>(Freelancer|Preferred Job) Location:<.*?>)(.*?)(<.*?>)(.*)"
match1_13 = "(.*)(<b>)(.*)"
match1_14 = "(.*)(<b>(Client Location:<.*?>|Country<.*?>:))(.*?)(<.*?>)(.*)"
match1_14b = "(.*)(<b>)(.*)"
match1_15 = "(.*)(<b>(Category:?<.*?>:?))(.*?)(<.*?>|<b>Skills<.*?>)(.*)"
match1_16 = "(.*)(<b>(Required skills|Desired Skills):<.*?>)(.*?)(<.*?>)(.*)"
match1_17 = "(.*)(Jobs:)(.*?)(\\))(.*)"
match1_18 = "&amp;|&gt;|&|<br>"
match1_19 = "(\\w+)(?!.*,)"
match1_20b = "\\/"
match1_21b = "[^a-zA-Z\\d,]+"
match1_22 = ".*Time Left.*\\(Ends(.*)\\) <.*?>"
match1_23 = "(.*)(<b>)(.*)"
# match1_24a = (
#     "(.*)(Fixed Price budget:<.*?>|Hourly budget.*Rate:|Budget:|Type and Budget|"
#     "Budget<.*?>:)(.*?)(<.*?>|, Jobs:)(.*)"
# )
match1_24b1 = "^((?!(budget|Budget|Hourly budget.*Rate)).)*$"
match1_24b2 = (
    r"(.*)((budget|Budget|Hourly budget.*Rate):?(<.*?>)?:?)\s*(.*?)(<.*?>|, Jobs:)(.*)"
)
match1_25 = "Under|Upto|Less than"
match1_26 = "^(?!.*-.*)(.*)"

regex1_rule = [
    make_regex_rule("title", match1_01, "$1"),
    make_regex_rule("k:marketplace", match1_02, "$3"),
    make_regex_rule("k:job_type", match1_03, "hourly"),
    make_regex_rule("k:job_type", match1_04, "fixed"),
    make_regex_rule("k:job_type", match1_05, "unknown"),
    make_regex_rule("k:job_type", ".*hr.*", "hourly"),
    make_regex_rule("k:job_type", ".*unknown.*", "unknown"),
    make_regex_rule("k:job_type", "^(?!.*(hourly|unknown).*).*", "fixed"),
    make_regex_rule("k:content", match1_06, "$1"),
    make_regex_rule("k:content", match1_07, "$3"),
    make_regex_rule("k:submissions", match1_08, "$3"),
    make_regex_rule("k:submissions", match1_09, "unknown"),
    make_regex_rule("k:author", match1_10, "$3"),
    make_regex_rule("k:author", match1_11, "unknown"),
    make_regex_rule("k:work_location", match1_12, "$4"),
    make_regex_rule("k:work_location", match1_13, "unknown"),
    make_regex_rule("k:client_location", match1_14, "$4"),
    make_regex_rule("k:client_location", match1_14b, "unknown"),
    make_regex_rule("k:tags", match1_15, "$4"),
    make_regex_rule("k:tags", match1_16, "$4"),
    make_regex_rule("k:tags", match1_17, "$3"),
    make_regex_rule("k:tags", match1_18, ""),
    make_regex_rule("k:tags", match1_19, "$1,"),
    make_regex_rule("k:tags", match1_20b, ","),
    make_regex_rule("k:tags", match1_21b, "-"),
    make_regex_rule("k:tags", "^-|-$", ""),
    make_regex_rule("k:tags", ",-|-,", ","),
    make_regex_rule("k:tags", "^,|,$", ""),
    make_regex_rule("k:due", match1_22, "$1"),
    make_regex_rule("k:due", match1_23, "unknown"),
    make_regex_rule("k:budget_raw", match1_24b1, "0", seriesmatch=False),
    make_regex_rule("k:budget_raw", match1_24b2, "$5", seriesmatch=False),
    make_regex_rule("k:budget_raw", "k", "000"),
    make_regex_rule("k:budget_raw", match1_25, "0 -"),
    make_regex_rule("k:budget_raw", "or less", "- 0"),
    make_regex_rule("k:budget_raw", match1_26, "$1 - $1"),
]

regex2_rule = [
    make_regex_rule("k:budget_raw1", "(.*) - (.*)", "$1"),
    make_regex_rule("k:budget_raw2", "(.*) - (.*)", "$2"),
]

regex3_rule = [
    make_regex_rule("k:budget_raw1_num", "[^\\d]*(\\d+\\.?\\d*).*", "$1"),
    make_regex_rule("k:budget_raw1_sym", "\\s*([$£€₹]).*", "$1"),
    make_regex_rule("k:budget_raw1_code", ".*(\\b[A-Z]{3}\\b).*", "$1"),
    make_regex_rule("k:budget_raw2_num", "[^\\d]*(\\d+\\.?\\d*).*", "$1"),
    make_regex_rule("k:budget_raw2_sym", "\\s*([$£€₹]).*", "$1"),
    make_regex_rule("k:budget_raw2_code", ".*(\\b[A-Z]{3}\\b).*", "$1"),
]

regex4_rule = [make_regex_rule("k:cur_code", "^(?![A-Z]{3}\\b)(.*)", DEF_CUR_CODE)]

strreplace_conf = StrReplaceConf(
    {
        "rule": [
            StrReplaceConfRule(find="$", replace="USD"),
            StrReplaceConfRule(find="£", replace="GBP"),
            StrReplaceConfRule(find="€", replace="EUR"),
            StrReplaceConfRule(find="₹", replace="INR"),
        ]
    }
)


regex4_conf = RegexConf(
    {
        "rule": [
            RegexConfRule(field="k:job_type_code", match="fixed", replace="1"),
            RegexConfRule(field="k:job_type_code", match="hourly", replace="2"),
            RegexConfRule(field="k:job_type_code", match="unknown", replace="3"),
        ]
    }
)

strconcat1_conf = StrconcatConf(
    {
        "part": [
            {"subkey": "k:budget_raw1_code", "type": "text"},
            {"subkey": "k:budget_raw2_code", "type": "text"},
        ]
    }
)

strconcat2_conf = StrconcatConf(
    {
        "part": [
            {"subkey": "k:budget_raw1_sym", "type": "text"},
            {"subkey": "k:budget_raw2_sym", "type": "text"},
        ]
    }
)

strconcat3_conf = StrconcatConf(
    {
        "part": [
            {"subkey": "k:budget_w_sym", "type": "text"},
            " (",
            {"subkey": "k:budget_converted_w_sym", "type": "text"},
            ")",
        ]
    }
)

strconcat4_conf = StrconcatConf(
    {"part": [{"subkey": "k:budget_full", "type": "text"}, " / hr"]}
)
tokenizer_conf = make_tokenizer(",", True, True)
substring1_conf = make_substring("0", "3")
substring2_conf = make_substring("1", "1")
currencyformat1_conf = CurrencyFormatRawConf(
    {"currency": {"subkey": "k:cur_code", "type": "text"}}
)
exchangerate_conf = make_exchangerate(DEF_CUR_CODE)
currencyformat2_conf = CurrencyFormatConf({"currency": DEF_CUR_CODE})
simplemath1_conf = make_simplemath("k:budget_raw2_num", "mean")
simplemath2_conf = make_simplemath("k:rate", "multiply")
test1: SkipIf = lambda item: bool(item.get("k:cur_code"))
test2: SkipIf = lambda item: item.get("k:cur_code") != DEF_CUR_CODE
test3: SkipIf = lambda item: item.get("k:cur_code") == DEF_CUR_CODE
test4: SkipIf = lambda item: item.get("k:job_type") != "hourly"

my_item = {
    "content": (
        "<p>Hello, I need to fix an application i am working on. Currently the rss has "
        "a cross origin problem, and i need to fix this.<br>\n<br>\nNext thing is i "
        "need to configure that the news will be read as an ion-list element, and a "
        "single article will be in a new page. with transition.<br>\n<br>\nThe "
        "application is in ionic + angular, so only experienced developers are welcome "
        "to this project.<br><br><b>Budget</b>: 10 EUR<br><b>Posted On</b>: December 27"
        ", 2014 13:32 UTC<br><b>ID</b>: 204946132<br><b>Category</b>: Web Development "
        "&gt; Web Programming<br><b>Skills</b>: Array<br><b>Country</b>: Israel<br><a "
        'href="https://www.odesk.com/jobs/Need-fix-Ionic-Rss-Reader-Application_'
        '%7E01d9a84fc5a0a79ddb?source=rss">click to apply</a></p>'
    ),
    "link": (
        "https://www.odesk.com/jobs/Need-fix-Ionic-Rss-Reader-Application_"
        "%7E01d9a84fc5a0a79ddb?source=rss"
    ),
    "pubDate": "December 27, 2014",
    "summary": (
        "<p>Hello, I need to fix an application i am working on. Currently the rss has "
        "a cross origin problem, and i need to fix this.<br>\n<br>\nNext thing is i "
        "need to configure that the news will be read as an ion-list element, and a "
        "single article will be in a new page. with transition.<br>\n<br>\nThe "
        "application is in ionic + angular, so only experienced developers are welcome "
        "to this project.<br><br><b>Budget</b>: 10 EUR<br><b>Posted On</b>: December 27"
        ", 2014 13:32 UTC<br><b>ID</b>: 204946132<br><b>Category</b>: Web Development "
        "&gt; Web Programming<br><b>Skills</b>: Array<br><b>Country</b>: Israel<br><a "
        'href="https://www.odesk.com/jobs/Need-fix-Ionic-Rss-Reader-Application_'
        '%7E01d9a84fc5a0a79ddb?source=rss">click to apply</a></p>'
    ),
    "title": "Need to fix Ionic Rss Reader Application - oDesk",
    "updated": "Sat, 27 Dec 2014 13:32:55 +0000",
    "y:id": None,
    "y:published": None,
    "y:title": "Need to fix Ionic Rss Reader Application - oDesk",
}

itembuilder_attrs = [{"key": k, "value": v} for k, v in my_item.items()]
itembuilder_conf = {"attrs": itembuilder_attrs}
fetch_conf = FetchConf({"url": "http://feeds.feedburner.com/guru/all"})
fetchdata_conf = FetchDataConf({"url": get_path("kazeeki2.json"), "path": "items"})


def parse_source(source: SyncPipe):
    pipe = (
        source.rename(conf=RenameConf({"rule": rename1_rule}))
        .regex(conf=RegexConf({"rule": regex1_rule}))
        .rename(conf=RenameConf({"rule": rename2_rule}))
        .regex(conf=RegexConf({"rule": regex2_rule}))
        .rename(conf=RenameConf({"rule": rename3_rule}))
        .regex(conf=RegexConf({"rule": regex3_rule}))
        .tokenizer(conf=tokenizer_conf, emit=False, assign="k:tags", field="k:tags")
        .simplemath(conf=simplemath1_conf, field="k:budget_raw1_num", assign="k:budget")
        .strconcat(conf=strconcat2_conf, assign="k:budget_sym")
        .substr(conf=substring2_conf, assign="k:budget_sym", field="k:budget_sym")
        .rename(
            conf=RenameConf(
                {
                    "rule": RenameConfRule(
                        newval="k:cur_code", field="k:budget_sym", copy=True
                    )
                }
            ),
            skip_if=test1,
        )
        .strreplace(conf=strreplace_conf, field="k:cur_code", assign="k:cur_code")
        .regex(conf=RegexConf({"rule": regex4_rule}))
        .rename(
            conf=RenameConf(
                {
                    "rule": RenameConfRule(
                        newval="k:job_type_code", field="k:job_type", copy=True
                    )
                }
            )
        )
        .regex(conf=regex4_conf)
        .hash(field="link", assign="id")
        .currencyformat(
            conf=currencyformat1_conf, field="k:budget", assign="k:budget_w_sym"
        )
        .exchangerate(conf=exchangerate_conf, field="k:cur_code", assign="k:rate")
        .simplemath(
            conf=simplemath2_conf, field="k:budget", assign="k:budget_converted"
        )
        .currencyformat(
            conf=currencyformat2_conf,
            field="k:budget_converted",
            assign="k:budget_converted_w_sym",
        )
        .rename(conf=RenameConf({"rule": rename4_rule}), skip_if=test2)
        .strconcat(conf=strconcat3_conf, assign="k:budget_full", skip_if=test3)
        .strconcat(conf=strconcat4_conf, assign="k:budget_full", skip_if=test4)
    )

    return list(pipe)


def print_content(output):
    pipe = list(output)
    pprint(pipe[0])
    print("count", len(pipe))


def pipe_kazeeki_full(context: Context | None = None, **_):
    if context and context.describe_input:
        output = []
    elif context and context.describe_dependencies:
        output = ["rename", "regex"]
    else:
        # source = SyncPipe("fetch", conf=fetch_conf, context=context)
        # source = SyncPipe("itembuilder", conf=itembuilder_conf, context=context)
        source = SyncPipe("fetchdata", conf=fetchdata_conf, context=context)
        output = parse_source(source)

    return output


if __name__ == "__main__":
    output = pipe_kazeeki_full(context=Context())
    print_content(output)
