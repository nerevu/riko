from typing import Required, TypedDict


# Geo/currency
class Region(TypedDict, total=False):
    code_2: Required[str]
    code_3: str
    continent: Required[str]
    country: str
    num: str


class CurrencyCode(TypedDict, total=False):
    code: Required[str]
    location: Required[str]
    name: str
    name_plural: str
    symbol: str
    symbol_native: str
    locale: str


type IPAddress = dict[str, str]
type Location = IPAddress | dict[str, float]
type AnyLocation = Region | CurrencyCode | Location | dict[str, float | str]
