# vim: sw=4:ts=4:expandtab

from itertools import chain
from os import path as p
from pprint import pprint

from riko import Context, get_path
from riko.collections import SyncPipe

PARENT = p.dirname(p.dirname(p.dirname(__file__)))

make_regex = lambda f, m, r: {"field": f, "match": m, "replace": r}
cdict = lambda *d: dict(chain.from_iterable(map(dict.items, d)))
pmatch = {"seriesmatch": False}


def make_simplemath(other, op):
    return {"OTHER": {"subkey": other, "type": "number"}, "OP": op}


def make_substring(start, length):
    return {"start": start, "length": length}


def make_exchangerate(quote, offline=True):
    return {"quote": quote, "default": DEF_CUR_CODE, "offline": offline}


def make_tokenizer(delimiter, dedupe=False, sort=False):
    return {"delimiter": delimiter, "dedupe": dedupe, "sort": sort}


def make_loop(field, assign, embed_conf, skip_if=None):
    conf = {
        "count": "all",
        "field": field,
        "embed": {"conf": embed_conf},
        "skip_if": skip_if,
    }

    kwargs = {
        "emit": False,
        "assign": assign,
    }

    return conf, kwargs


DEF_CUR_CODE = "USD"

rename1_rule = [
    {"newval": "", "field": "y:title", "copy": False},
    {"newval": "", "field": "content", "copy": False},
    {"newval": "k:posted", "field": "y:published", "copy": False},
    {"newval": "k:job_type", "field": "summary", "copy": True},
    {"newval": "k:content", "field": "summary", "copy": True},
    {"newval": "k:work_location", "field": "summary", "copy": True},
    {"newval": "k:client_location", "field": "summary", "copy": True},
    # {"newval": "k:category", "field": "summary", "copy": True},
    {"newval": "k:tags", "field": "summary", "copy": True},
    {"newval": "k:due", "field": "summary", "copy": True},
    {"newval": "k:submissions", "field": "summary", "copy": True},
    {"newval": "k:budget_raw", "field": "summary", "copy": True},
    {"newval": "k:marketplace", "field": "link", "copy": True},
    {"newval": "k:author", "field": "title", "copy": True},
]

rename2_rule = [
    {"newval": "k:budget_raw1", "field": "k:budget_raw", "copy": True},
    {"newval": "k:budget_raw2", "field": "k:budget_raw", "copy": True},
]

rename3_rule = [
    {"newval": "k:budget_raw1_num", "field": "k:budget_raw1", "copy": True},
    {"newval": "k:budget_raw1_sym", "field": "k:budget_raw1", "copy": True},
    {"newval": "k:budget_raw1_code", "field": "k:budget_raw1", "copy": True},
    {"newval": "k:budget_raw2_num", "field": "k:budget_raw2", "copy": True},
    {"newval": "k:budget_raw2_sym", "field": "k:budget_raw2", "copy": True},
    {"newval": "k:budget_raw2_code", "field": "k:budget_raw2", "copy": True},
]

rename4_rule = [{"newval": "k:budget_full", "field": "k:budget_w_sym", "copy": True}]

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
match1_18 = "&gt;|<br>"
match1_19 = "(\\w+)(?!.*,)"
match1_20b = "\\/"
match1_21b = "[^a-zA-Z\\d,]+"
match1_22 = ".*Time Left.*\\(Ends(.*)\\) <.*?>"
match1_23 = "(.*)(<b>)(.*)"
# match1_24a = "(.*)(Fixed Price budget:<.*?>|Hourly budget.*Rate:|Budget:|Type and Budget|Budget<.*?>:)(.*?)(<.*?>|, Jobs:)(.*)"
match1_24b1 = "^((?!(budget|Budget|Hourly budget.*Rate)).)*$"
match1_24b2 = (
    r"(.*)((budget|Budget|Hourly budget.*Rate):?(<.*?>)?:?)\s*(.*?)(<.*?>|, Jobs:)(.*)"
)
match1_25 = "Under|Upto|Less than"
match1_26 = "^(?!.*-.*)(.*)"

regex1_rule = [
    make_regex("title", match1_01, "$1"),
    make_regex("k:marketplace", match1_02, "$3"),
    make_regex("k:job_type", match1_03, "hourly"),
    make_regex("k:job_type", match1_04, "fixed"),
    make_regex("k:job_type", match1_05, "unknown"),
    make_regex("k:job_type", ".*hr.*", "hourly"),
    make_regex("k:job_type", ".*unknown.*", "unknown"),
    make_regex("k:job_type", "^(?!.*(hourly|unknown).*).*", "fixed"),
    make_regex("k:content", match1_06, "$1"),
    make_regex("k:content", match1_07, "$3"),
    make_regex("k:submissions", match1_08, "$3"),
    make_regex("k:submissions", match1_09, "unknown"),
    make_regex("k:author", match1_10, "$3"),
    make_regex("k:author", match1_11, "unknown"),
    make_regex("k:work_location", match1_12, "$4"),
    make_regex("k:work_location", match1_13, "unknown"),
    make_regex("k:client_location", match1_14, "$4"),
    make_regex("k:client_location", match1_14b, "unknown"),
    make_regex("k:tags", match1_15, "$4"),
    make_regex("k:tags", match1_16, "$4"),
    make_regex("k:tags", match1_17, "$3"),
    make_regex("k:tags", match1_18, ""),
    make_regex("k:tags", match1_19, "$1,"),
    make_regex("k:tags", match1_20b, ","),
    make_regex("k:tags", match1_21b, "-"),
    make_regex("k:tags", "^-|-$", ""),
    make_regex("k:tags", ",-|-,", ","),
    make_regex("k:tags", "^,|,$", ""),
    make_regex("k:due", match1_22, "$1"),
    make_regex("k:due", match1_23, "unknown"),
    cdict(pmatch, make_regex("k:budget_raw", match1_24b1, "0")),
    cdict(pmatch, make_regex("k:budget_raw", match1_24b2, "$5")),
    make_regex("k:budget_raw", "k", "000"),
    make_regex("k:budget_raw", match1_25, "0 -"),
    make_regex("k:budget_raw", "or less", "- 0"),
    make_regex("k:budget_raw", match1_26, "$1 - $1"),
]

regex2_rule = [
    make_regex("k:budget_raw1", "(.*) - (.*)", "$1"),
    make_regex("k:budget_raw2", "(.*) - (.*)", "$2"),
]

regex3_rule = [
    make_regex("k:budget_raw1_num", "[^\\d]*(\\d+\\.?\\d*).*", "$1"),
    make_regex("k:budget_raw1_sym", "\\s*([$£€₹]).*", "$1"),
    make_regex("k:budget_raw1_code", ".*(\\b[A-Z]{3}\\b).*", "$1"),
    make_regex("k:budget_raw2_num", "[^\\d]*(\\d+\\.?\\d*).*", "$1"),
    make_regex("k:budget_raw2_sym", "\\s*([$£€₹]).*", "$1"),
    make_regex("k:budget_raw2_code", ".*(\\b[A-Z]{3}\\b).*", "$1"),
]

regex4_rule = [make_regex("k:cur_code", "^(?![A-Z]{3}\\b)(.*)", DEF_CUR_CODE)]

strreplace_conf = {
    "RULE": [
        {"find": "$", "replace": "USD"},
        {"find": "£", "replace": "GBP"},
        {"find": "€", "replace": "EUR"},
        {"find": "₹", "replace": "INR"},
    ]
}


regex4_conf = {
    "RULE": [
        {"field": "k:job_type_code", "match": "fixed", "replace": "1"},
        {"field": "k:job_type_code", "match": "hourly", "replace": "2"},
        {"field": "k:job_type_code", "match": "unknown", "replace": "3"},
    ]
}

strconcat1_conf = {
    "part": [{"subkey": "k:budget_raw1_code"}, {"subkey": "k:budget_raw2_code"}]
}

strconcat2_conf = {
    "part": [{"subkey": "k:budget_raw1_sym"}, {"subkey": "k:budget_raw2_sym"}]
}

strconcat3_conf = {
    "part": [
        {"subkey": "k:budget_w_sym"},
        " (",
        {"subkey": "k:budget_converted_w_sym"},
        ")",
    ]
}

strconcat4_conf = {"part": [{"subkey": "k:budget_full"}, " / hr"]}

tokenizer_conf = make_tokenizer(",", True, True)
substring1_conf = make_substring("0", "3")
substring2_conf = make_substring("0", "1")
currencyformat1_conf = {"currency": {"subkey": "k:cur_code"}}
exchangerate_conf = make_exchangerate(DEF_CUR_CODE, True)
currencyformat2_conf = {"currency": DEF_CUR_CODE}
simplemath1_conf = make_simplemath("k:budget_raw2_num", "mean")
simplemath2_conf = make_simplemath("k:rate", "multiply")
test1 = lambda item: item.get("k:cur_code")
test2 = lambda item: item.get("k:cur_code") != DEF_CUR_CODE
test3 = lambda item: item.get("k:cur_code") == DEF_CUR_CODE
test4 = lambda item: item.get("k:job_type") != "hourly"

my_item = {
    "content": '<p>Hello, I need to fix an application i am working on. Currently the rss has a cross origin problem, and i need to fix this.<br>\n<br>\nNext thing is i need to configure that the news will be read as an ion-list element, and a single article will be in a new page. with transition.<br>\n<br>\nThe application is in ionic + angular, so only experienced developers are welcome to this project.<br><br><b>Budget</b>: 10 EUR<br><b>Posted On</b>: December 27, 2014 13:32 UTC<br><b>ID</b>: 204946132<br><b>Category</b>: Web Development &gt; Web Programming<br><b>Skills</b>: Array<br><b>Country</b>: Israel<br><a href="https://www.odesk.com/jobs/Need-fix-Ionic-Rss-Reader-Application_%7E01d9a84fc5a0a79ddb?source=rss">click to apply</a></p>',
    "link": "https://www.odesk.com/jobs/Need-fix-Ionic-Rss-Reader-Application_%7E01d9a84fc5a0a79ddb?source=rss",
    "pubDate": "December 27, 2014",
    "summary": '<p>Hello, I need to fix an application i am working on. Currently the rss has a cross origin problem, and i need to fix this.<br>\n<br>\nNext thing is i need to configure that the news will be read as an ion-list element, and a single article will be in a new page. with transition.<br>\n<br>\nThe application is in ionic + angular, so only experienced developers are welcome to this project.<br><br><b>Budget</b>: 10 EUR<br><b>Posted On</b>: December 27, 2014 13:32 UTC<br><b>ID</b>: 204946132<br><b>Category</b>: Web Development &gt; Web Programming<br><b>Skills</b>: Array<br><b>Country</b>: Israel<br><a href="https://www.odesk.com/jobs/Need-fix-Ionic-Rss-Reader-Application_%7E01d9a84fc5a0a79ddb?source=rss">click to apply</a></p>',
    "title": "Need to fix Ionic Rss Reader Application - oDesk",
    "updated": "Sat, 27 Dec 2014 13:32:55 +0000",
    "y:id": None,
    "y:published": None,
    "y:title": "Need to fix Ionic Rss Reader Application - oDesk",
}

itembuilder_attrs = [{"key": k, "value": v} for k, v in my_item.items()]
itembuilder_conf = {"attrs": itembuilder_attrs}
fetch_conf = {"URL": "http://feeds.feedburner.com/guru/all"}
fetchdata_conf = {"URL": get_path("kazeeki2.json"), "path": "items"}


def parse_source(source):
    pipe = (
        source.rename(conf={"RULE": rename1_rule})
        .regex(conf={"RULE": regex1_rule})
        .rename(conf={"RULE": rename2_rule})
        .regex(conf={"RULE": regex2_rule})
        .rename(conf={"RULE": rename3_rule})
        .regex(conf={"RULE": regex3_rule})
        .tokenizer(conf=tokenizer_conf, field="k:tags")
        .simplemath(conf=simplemath1_conf, field="k:budget_raw1_num", assign="k:budget")
        .strconcat(conf=strconcat1_conf, assign="k:cur_code")
        .substr(conf=substring1_conf, field="k:cur_code")
        .strconcat(conf=strconcat2_conf, assign="k:budget_sym")
        .substr(conf=substring2_conf, field="k:budget_sym")
        .rename(
            conf={
                "RULE": {"newval": "k:cur_code", "field": "k:budget_sym", "copy": True}
            },
            skip_if=test1,
        )
        .strreplace(conf=strreplace_conf, field="k:cur_code", assign="k:cur_code")
        .regex(conf={"RULE": regex4_rule})
        .rename(
            conf={
                "RULE": {
                    "newval": "k:job_type_code",
                    "field": "k:job_type",
                    "copy": True,
                }
            }
        )
        .regex(conf=regex4_conf)
        .hash(field="link", assign="id")
        .currencyformat(
            conf=currencyformat1_conf, field="k:budget", assign="k:budget_w_sym"
        )
        # .exchangerate(conf=exchangerate_conf, field="k:cur_code", assign="k:rate")
        # .simplemath(conf=simplemath2_conf, field="k:budget", assign="k:budget_converted")
        .currencyformat(
            conf=currencyformat2_conf,
            field="k:budget_converted",
            assign="k:budget_converted_w_sym",
        )
        .rename(conf={"RULE": rename4_rule}, skip_if=test2)
        .strconcat(conf=strconcat3_conf, assign="k:budget_full", skip_if=test3)
        .strconcat(conf=strconcat4_conf, assign="k:budget_full", skip_if=test4)
    )

    return list(pipe)


def print_content(output):
    pipe = list(output)
    pprint(pipe[0])
    print("count", len(pipe))


def pipe_kazeeki_full(context: Context):
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
    output = pipe_kazeeki_full(Context())
    print_content(output)
