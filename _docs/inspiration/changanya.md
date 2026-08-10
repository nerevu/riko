# changanya

Interesting (non-cryptographic) hashes implemented in pure Python 3. Included so far:

 * Bloom filters
 * Simhash (Charikar similarity hashes)
 * Nilsimsa signatures
 * geohashes

Each hash is implemented as its own type extended from the base class `Hashtype`.

This is a fork of [sangelone's](https://github.com/sangelone/changanya) repo
that I ported to Python 3 and added various enhancements such as [decimal precision](#precision) and [duplicate detection](#deduplication).

To install the latest version, you can `pip install --user changanya` or (inside a [virtualenv](http://www.virtualenv.org/en/latest/index.html)) `pip install changanya`.

---

## Simhash

Charikar similarity is most useful for creating 'fingerprints' of
documents or metadata so you can quickly find duplicates or cluster
items. It operates on strings by treating each word as its
own token. Order does not matter, as in the bag-of-words model.

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

This functionality was ported from [leonsim/simhash](https://github.com/leonsim/simhash) [1].

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

[1] http://leons.im/posts/a-python-implementation-of-simhash-algorithm/

#### Finding all duplicates

This functionality was ported from [seomoz/simhash-cpp](https://github.com/seomoz/simhash-cpp) [2].

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

[2] https://moz.com/devblog/near-duplicate-detection/

## Bloom

The Bloom filter is a space-efficient probabilistic data structure that is
used to test whether an element is a member of a set. False positives are
possible, but false negatives are not. Elements can be added to the set but
not removed.

This implantation uses SHA-1 from Python's hashlib, but you can swap that out
with any other 160-bit hash function. Also keep in mind that it starts off very
sparse and becomes more dense (and false-positive-prone) as you add more elements.

Here is the basic use case:

```python
>>> from changanya.bloom import Bloomfilter
>>> hash1 = Bloomfilter('test')
>>> hash1.hashbits, hash1.num_hashes     # default values (see below)
(28756, 7)
>>> hash1.add('test string')
>>> 'test string' in hash1
True
>>> 'holy diver' in hash1
False
>>> [hash1.add(word) for word in 'some tokens to add to the filter'.split()]
>>> 'tokens' in hash1
True
```

The hash length and number of internal hashes used for the digest are
automatically determined using your values for `capacity` and `false_pos_rate`.
The capacity is the upper bound on the number of items you wish to add. A lower
false-positive rate will create a larger, but more accurate, filter.

```python
>>> hash2 = Bloomfilter(capacity=100, false_pos_rate=0.01)
>>> hash2.hashbits, hash2.num_hashes
(959, 7)
>>> hash3 = Bloomfilter(capacity=1000000, false_pos_rate=0.01)
>>> hash3.hashbits, hash3.num_hashes
(9585059, 7)
>>> hash4 = Bloomfilter(capacity=1000000, false_pos_rate=0.0001)
>>> hash4.hashbits, hash4.num_hashes
(19170117, 14)
```

The hash grows in size to accommodate the number of items you wish to add,
but remains sparse until you are done adding the projected number of items:

```python
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

It is a hierarchical spatial data structure which subdivides space into grids.
Geohashes offer properties like arbitrary precision and the possibility of
gradually removing characters from the end of the code to reduce its size and precision. Consequently, nearby places will often (but not always) present
similar prefixes. Also, the longer a shared prefix is, the closer the two
places are to each other. For this implementation, the default precision is
(at most) 8 (base32) characters long [1].

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

GeoHash uses the [Decimal](https://docs.python.org/3/library/decimal.html) type to enforce precision

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

[Related paper](https://web.archive.org/web/20121206233111/http://spdp.dti.unimi.it/papers/pdcs04.pdf) and [original reference](https://web.archive.org/web/20150512025912/http://ixazon.dynip.com/~cmeclax/nilsimsa.html).

*The Nilsimsa hash does not output the same data as the
reference implementation.* **Use at your own risk.**

## License

changanya is distributed under the [MIT License](http://opensource.org/licenses/MIT).
