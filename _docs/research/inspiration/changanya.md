---
source: ../../../../changanya/README.md
---

# changanya

Interesting (non-cryptographic) hashes implemented in pure Python 3. Included so far:

- Bloom filters
- Simhash (Charikar similarity hashes)
- Nilsimsa signatures (currently broken; see [Nilsimsa](#nilsimsa))
- geohashes

Each hash is implemented as its own type extended from the base class `Hashtype`.

This is a fork of [sangelone's](https://github.com/sangelone/changanya) repo that I
ported to Python 3 and added various enhancements such as
[decimal precision](#precision) and [duplicate detection](#deduplication).

To install the latest version, you can `pip install --user changanya` or (inside a
[virtualenv](http://www.virtualenv.org/en/latest/index.html)) `pip install changanya`.

---

## Shared behavior

`Simhash`, `Bloomfilter`, and `Nilsimsa` store their value as an integer in `.hash`, and
`print()`/`str()`, `int()`, `float()`, and `.hex()` show that value. `Geohash` also
extends `Hashtype`, but its `.hash` is a base32 string (see [Geohash](#geohash)).

| Class | Module | Default `hashbits` |
| ----- | ------ | ------------------ |
| `Simhash` | `changanya.simhash` | 64 |
| `Bloomfilter` | `changanya.bloom` | derived from `capacity` and `false_pos_rate` (see [Bloom](#bloom)) |
| `Nilsimsa` | `changanya.nilsimsa` | 256 |
| `Hashtype` (base) | `changanya.hashtype` | 96 |

- `a.hamming_distance(b)` counts the differing bits.
- `a.similarity(b)` returns `(hashbits - hamming_distance) / hashbits`, a float from 0.0
  to 1.0. It raises `TypeError` if `b` is a different hash type and `ValueError` if the
  two have different `hashbits`.
- Equality, ordering, and `hash()` use the hash value only. Two objects built from
  different data but with the same hash value are equal and collapse to one member of a
  `set`.

## Simhash

Charikar similarity is most useful for creating 'fingerprints' of
documents or metadata so you can quickly find duplicates or cluster
items. Token order does not matter, as in the bag-of-words model.

### Tokenization

`Simhash(data, hashbits=64, **kwargs)` splits a string into tokens by this rule
(`changanya/simhash.py:65-87`):

- If the string has fewer than `min_words` whitespace-separated words (default 4), each
  word is lowercased and broken into character trigrams; a word shorter than 3
  characters is kept whole. `'Hello big World'` becomes `hel`, `ell`, `llo`, `big`,
  `wor`, `orl`, `rld`.
- Otherwise the raw `str.split()` words are the tokens, with case and punctuation kept.
  `'Hello, big wide World!'` becomes `Hello,`, `big`, `wide`, `World!`.
- Data that is not a string (has no `.split()`) is iterated, and each element is a
  token.

So short strings compare case-insensitively and long ones do not:

```python
>>> from changanya.simhash import Simhash
>>> Simhash('Hello World') == Simhash('hello world')
True
>>> Simhash('Hello big wide World') == Simhash('hello big wide world')
False
>>> Simhash('Hello big wide World', min_words=10) == Simhash('hello big wide world', min_words=10)
True
```

| Keyword | Default | Effect |
| ------- | ------- | ------ |
| `hashbits` | `64` | bit length of the hash |
| `min_words` | `4` | word count at or above which raw words are used instead of trigrams |
| `force_words` | off | always use the raw `split()` words |
| `force_chars` | off | always use the individual characters as tokens (wins over `force_words`) |
| `id` | `id(self)` | identifier used by `SimhashIndex` to tell entries apart |

### Basic usage

```python
>>> from changanya.simhash import Simhash
>>>
>>> hash1 = Simhash('This is a test string one.')
>>> hash2 = Simhash('This is a test string TWO.')
>>> hash1
<changanya.simhash.Simhash object at 0x...>

>>> # All hash objects print their hash
>>> print(hash1)
11537571312501063112
>>> print(hash2)
11537571196679550920

>>> # Check the similarity of two hashes (calculated % of bits in common
>>> # according to their hamming distance)
>>> hash1.similarity(hash2)
0.890625

>>> # You can compare hashes of the same type
>>> hash1 < hash2
False
>>> hashes = [hash2, hash1]
>>> for item in hashes:
...     print(item)
11537571196679550920
11537571312501063112

>>> # Because comparisons work, so does sorting
>>> hashes.sort(reverse=True)
>>> for item in hashes:
...     print(item)
11537571312501063112
11537571196679550920

>>> # You can extend hashes to any bitlength using the `hashbits` parameter.
>>> hash3 = Simhash('this is yet another test', hashbits=8)
>>> hash3.hex()
'0x18'
>>> hash4 = Simhash('extremely long hash bitlength', hashbits=2048)
>>> hash4.hex()
'0xf00020585012016060260443bab0f7d76fde5549a6857ec'

>>> # But be careful; you can only compare equal-length hashes!
>>> hash3.similarity(hash4)
Traceback (most recent call last):
ValueError: Hashes must be of equal size to find similarity
```

### Deduplication

#### Finding individual duplicates

This functionality was ported from [leonsim/simhash](https://github.com/leonsim/simhash)
[1].

`SimhashIndex(simhashes, bits=2, num_blocks=4)` takes an iterable of `Simhash` objects
of equal `hashbits`. `bits` is the largest Hamming distance counted as a duplicate.
`num_blocks` is the number of key blocks each hash is split into and must not exceed
`hashbits // 2` (otherwise `ValueError`). `find_dupes(simhash)` looks up every block key
of `simhash` and yields each indexed entry within `bits` bits, once per `id`.

```python
>>> from changanya.simhash import SimhashIndex
>>>
>>> # Create some data to hash
>>> data = [
...     'How are you? I Am fine. blar blar blar blar blar Thanks.',
...     'How are you i am fine. blar blar blar blar blar than',
...     'This is simhash test.']
>>>
>>> # Create an array of Simhash objects
>>> hashes = [Simhash(text) for text in data]
>>>
>>> for simhash in hashes:
...     print(simhash)
1318951168287673739
1318951168283479435
13366613251191922586

>>> # Initialize the Simhash index
>>>
>>> # By default, the index will divide each hash into 4 blocks and consider
>>> # hashes to be duplicates if they have, at most, 2 bits that differ
>>> index = SimhashIndex(hashes)
>>>
>>> # Create a Simhash object for the content you want to find duplicates of
>>> simhash = Simhash('How are you im fine. blar blar blar blar thank')
>>> simhash.hash
1318986352659762571

>>> # The result of calling `find_dupes` with a simhash object as the
>>> # argument is an iterator of duplicate simhash objects
>>> dupes = index.find_dupes(simhash)
>>> first_dupe = next(dupes)

>>> # Here, we see that the first detected duplicate is the first entry in
>>> # the `data` we initially created
>>> first_dupe == hashes[0]
True

>>> # You can also add new items to the index. Here we add the simhash
>>> # object we created above
>>> index.add(simhash)

>>> # This time, the first detected duplicate is the simhash object we just
>>> # added
>>> first_dupe = next(index.find_dupes(simhash))
>>> first_dupe == simhash
True
```

[1] <http://leons.im/posts/a-python-implementation-of-simhash-algorithm/>

#### Finding all duplicates

This functionality was ported from
[seomoz/simhash-cpp](https://github.com/seomoz/simhash-cpp) [2].

`find_all_dupes(non_dupes=None)` yields pairs of indexed hashes within `bits` bits of
each other. `non_dupes` is an optional set of `frozenset({id1, id2})` pairs to skip. A
non-empty set is updated in place with every pair yielded; an empty one is ignored and a
fresh set is used instead.

Despite the name, it does not find every duplicate pair:

- For each block permutation it compares only the hashes that share the masked prefix of
  the smallest permuted hash (`changanya/simhash.py:225-231`). Duplicate pairs in any
  other prefix group are never compared. For example, an index of the hashes `1`, `3`,
  `M ^ 1`, and `M ^ 3` (with `M = 2 ** 64 - 1`) yields only the pair (`1`, `3`),
  although `M ^ 1` and `M ^ 3` also differ by one bit and are found when indexed on
  their own.
- It scans only the hashes the index was created with. `add()` puts a hash in the lookup
  buckets used by `find_dupes` but not in that list (`changanya/simhash.py:163-167`,
  `:222`), so added hashes never appear in `find_all_dupes` results.

The example below works because its one duplicate pair is in the scanned group. The
`simhash` added in the previous example does not take part.

```python
>>> # Let's use the same Simhash index we created above
>>>
>>> # The result of calling `find_all_dupes` is an iterator of pairs of
>>> # duplicate simhash objects
>>> all_dupes = index.find_all_dupes()

>>> # Now let's extract first pair of duplicate objects
>>> first_pair = next(all_dupes)
>>> dupe1, dupe2 = first_pair

>>> # Here, we see that the first detected pair of duplicates are the first
>>> # two entries in the `data` we initially created
>>> {dupe1, dupe2} == {hashes[0], hashes[1]}
True
>>> # And, as expected, they are very similar
>>> dupe1.similarity(dupe2)
0.984375
>>>
>>> # This is because they only differ by one bit
>>> dupe1.hamming_distance(dupe2)
1
```

[2] <https://moz.com/devblog/near-duplicate-detection/>

## Bloom

The Bloom filter is a space-efficient probabilistic data structure that is
used to test whether an element is a member of a set. False positives are
possible, but false negatives are not. Elements can be added to the set but
not removed.

This implementation uses SHA-1 from Python's hashlib. The hash function is fixed in
`Bloomfilter._hashes` (`changanya/bloom.py:74`); there is no option to swap it. Also
keep in mind that the filter starts off very sparse and becomes more dense (and
false-positive-prone) as you add more elements.

`Bloomfilter(data='', capacity=3000, false_pos_rate=0.01)` takes an optional initial
string, or an iterable of strings, to add.

Here is the basic use case:

```python
>>> from changanya.bloom import Bloomfilter
>>> hash1 = Bloomfilter('test')
>>> hash1.hashbits, hash1.num_hashes     # from the defaults capacity=3000, false_pos_rate=0.01
(28756, 7)
>>> hash1.add('test string')
>>> 'test string' in hash1
True
>>> 'holy diver' in hash1
False
>>> for word in 'some tokens to add to the filter'.split():
...     hash1.add(word)
>>> 'tokens' in hash1
True
```

### Size and number of hashes

The filter size (`hashbits`) and the number of internal hashes (`num_hashes`) are
determined from `capacity` and `false_pos_rate` (`changanya/bloom.py:89-102`):

- `hashbits = ceil(-capacity * ln(false_pos_rate) / ln(2) ** 2)`
- `num_hashes = ceil(ln(2) * hashbits / capacity)`, which works out to about
  `log2(1 / false_pos_rate)` whatever the capacity

The capacity is the upper bound on the number of items you wish to add. A lower
false-positive rate gives a larger `hashbits` and more hashes, but two limits in the
code mean the configured rate is not always what you get:

- **Bit positions stop at 2\*\*20.** Each hash position is read from a 5-hex-digit
  (20-bit) slice of the SHA-1 digest and then reduced modulo `hashbits`
  (`changanya/bloom.py:83-85`). Every position is therefore below 1,048,576. When
  `hashbits` is larger than that (for example `capacity` above about 109,000 at the
  default rate of 0.01), only the first 1,048,576 bits are used, and the real
  false-positive rate is that of a 1,048,576-bit filter, not the configured one. There
  are still no false negatives.
- **Eight or more hashes fail on Python 3.** For every 8 hashes the code extends the
  digest with `m.update(str(i))`, which needs bytes on Python 3
  (`changanya/bloom.py:79-80`). Any filter with `num_hashes >= 8`, i.e. a
  `false_pos_rate` below 1/128 (about 0.0078), raises
  `TypeError: Strings must be encoded before hashing` on `add()`, on `in`, and when
  created with initial data. Creating it empty succeeds.

```python
>>> hash2 = Bloomfilter(capacity=100, false_pos_rate=0.01)
>>> hash2.hashbits, hash2.num_hashes
(959, 7)
>>> hash3 = Bloomfilter(capacity=1000000, false_pos_rate=0.01)
>>> hash3.hashbits, hash3.num_hashes
(9585059, 7)
>>> # Only the first 2**20 bits are ever set
>>> for i in range(2000):
...     hash3.add(str(i))
>>> hash3.hash.bit_length() <= 2 ** 20
True
>>> hash3.hash.bit_length()
1048524

>>> # 14 hashes: the filter can be created but not used
>>> hash4 = Bloomfilter(capacity=1000000, false_pos_rate=0.0001)
>>> hash4.hashbits, hash4.num_hashes
(19170117, 14)
>>> hash4.add('test')
Traceback (most recent call last):
TypeError: Strings must be encoded before hashing
```

The hash grows in size to accommodate the number of items you wish to add,
but remains sparse until you are done adding the projected number of items.
For example (intended behavior; on Python 3,
`hash4.add` fails as shown above, `hex()` returns the hex string of a mostly
empty integer, and `zlib.compress` needs bytes, so it does not run as written):

```pycon
>>> import zlib
>>> len(hash4.hex())
250899
>>> len(zlib.compress(hash4.hex()))
1068
```

## Geohash

Geohash is a latitude/longitude geocode system invented by
Gustavo Niemeyer when writing the web service at geohash.org, and put
into the public domain.

It is a hierarchical spatial data structure which subdivides space into grids. Geohashes
offer properties like arbitrary precision and the possibility of gradually removing
characters from the end of the code to reduce its size and precision. Consequently,
nearby places will often (but not always) present similar prefixes. Also, the longer a
shared prefix is, the closer the two places are to each other. For this implementation,
the default precision is (at most) 8 (base32) characters long [1].

### Basic Usage

```python
>>> from changanya.geohash import Geohash
>>>
>>> # Enter locations as (<latitude>, <longitude>), and use strings to avoid
>>> # floating point imprecision
>>> here = Geohash('33.050500000000', '-1.024', precision=4)
>>> there = Geohash('34.5000000000', '-2.500', precision=4)

>>> # View the hashes
>>> here.hash, there.hash
('evzs', 'eynk')

>>> # View the location at the initialized precision level
>>> here.decode()
(Decimal('33.050500'), Decimal('-1.024'))

>>> # View the distance between the two locations
>>> here.distance_in_miles(there)
Decimal('131.24743')

>>> # Let's reencode the object at a higher precision level to get a longer
>>> # hash
>>> here.encode(precision=8)
>>> here.hash
'evzk08wt'

>>> # We can also decode arbitrary hashes
>>> here.decode('evzk08wt')
(Decimal('33.0504798889'), Decimal('-1.024'))

>>> # The number of displayed decimal places increases as well
>>> here.decode()
(Decimal('33.0505000000'), Decimal('-1.024'))
>>> here.distance_in_miles(there)
Decimal('131.247434251')
```

### Precision

GeoHash uses the [Decimal](https://docs.python.org/3/library/decimal.html) type to
enforce precision

```python
>>> # We can't gain more precision than we started with
>>> here.encode(precision=16)
>>> here.precision
10
>>>
>>> # The is because the initial location only provided a precision of 10
>>> here.max_precision
10
>>>
>>> # So we can show a maximum of 10 characters
>>> here.hash
'evzk08wm57'

>>> # Likewise we can't show a location more precise than what was given
>>> here.decode()
(Decimal('33.050500000000'), Decimal('-1.024'))
>>>
>>> # Since the `there` object is less precise than the `here` object, the
>>> # number of displayed `distance_in_miles` decimal places is limited by
>>> # `there`
>>> there.max_precision
8
>>> here.distance_precision
8
>>> here.distance_in_miles(there)
Decimal('131.247434251')
```

[1] In order to achieve this level of precision, you must input a latitude with
at least 10 decimal places.

## Nilsimsa

Most useful for filtering spam by creating signatures of documents to
find near-duplicates. Charikar similarity hashes can be used on any
datastream, whereas Nilsimsa is a digest ideal for documents (language
doesn't matter) because it uses histograms of *rolling* trigraphs instead
of the usual bag-of-words model where order doesn't matter.

[Related paper](https://web.archive.org/web/20121206233111/http://spdp.dti.unimi.it/papers/pdcs04.pdf)
and
[original reference](https://web.archive.org/web/20150512025912/http://ixazon.dynip.com/~cmeclax/nilsimsa.html).

The class is `changanya.nilsimsa.Nilsimsa(data='', hashbits=256)`; `data` must be a
string. It shares `similarity` and `hamming_distance` with the other hash types.

Creating a `Nilsimsa` object currently fails for any input, including the empty default.
The base class computes the hash in its constructor (`changanya/hashtype.py:21`), before
`Nilsimsa.__init__` sets the counters the digest reads (`changanya/nilsimsa.py:45-48`):

```python
>>> from changanya.nilsimsa import Nilsimsa
>>> Nilsimsa('hello world')
Traceback (most recent call last):
AttributeError: 'Nilsimsa' object has no attribute 'count'
```

*The Nilsimsa code also does not output the same data as the reference implementation.*

## Known issues

- `Nilsimsa(...)` raises `AttributeError: 'Nilsimsa' object has no attribute 'count'`
  for every input, because `Hashtype.__init__` calls `create_hash` before
  `Nilsimsa.__init__` sets `count`, `acc`, and `last` (`changanya/hashtype.py:21`,
  `changanya/nilsimsa.py:45-48`).
- `SimhashIndex.find_all_dupes` misses duplicate pairs outside the prefix group of the
  smallest permuted hash (`changanya/simhash.py:225-231`).
- `SimhashIndex.find_all_dupes` ignores hashes added with `add()` after the index was
  created, because it iterates only the initial list (`changanya/simhash.py:163-167`,
  `:222`).
- `Simhash` is case-insensitive for strings under `min_words` words and case-sensitive
  (punctuation included) at or above it (`changanya/simhash.py:78-87`), so the same text
  in different case may or may not hash equal depending on its length.
- `Bloomfilter` bit positions never exceed 2\*\*20 because they come from 20-bit digest
  slices (`changanya/bloom.py:83-85`); filters with `hashbits` above 1,048,576 have a
  higher false-positive rate than configured.
- `Bloomfilter` with 8 or more hashes (`false_pos_rate` below about 0.0078) raises
  `TypeError: Strings must be encoded before hashing` on `add()`, `in`, and construction
  with data, because `m.update(str(i))` passes a `str` to SHA-1
  (`changanya/bloom.py:79-80`).

## License

changanya is distributed under the [MIT License](http://opensource.org/licenses/MIT).
