Changelog
=========

%%version%% (unreleased)
------------------------

Bugfixes
~~~~~~~~

- Store downloaded packages in wheel dir. [Reuben Cummings]

- Fix prefix generation. [Reuben Cummings]

v0.35.1 (2016-07-22)
--------------------

Bugfixes
~~~~~~~~

- Fix makefile lint command. [Reuben Cummings]

- Update pygogo requirement (fixes #2) [Reuben Cummings]

v0.35.0 (2016-07-19)
--------------------

New
~~~

- Limit the number of unique items tracked. [Reuben Cummings]

- Add grouping ability to count pipe. [Reuben Cummings]

Bugfixes
~~~~~~~~

- Fix processor metadata. [Reuben Cummings]

v0.34.0 (2016-07-19)
--------------------

New
~~~

- Add list element searching to microdom. [Reuben Cummings]

- Add more operations to filter pipes. [Reuben Cummings]

Changes
~~~~~~~

- Merge async_pmap and async_imap. [Reuben Cummings]

- Change deferToProcess name and arguments. [Reuben Cummings]

- Rename modules/functions, and update docs. [Reuben Cummings]

Bugfixes
~~~~~~~~

- Force getElementsByTagName to return child. [Reuben Cummings]

- Only use FakeReactor when actually needed. [Reuben Cummings]

- Fix async html parsing. [Reuben Cummings]

- Prevent IndexError. [Reuben Cummings]

- Fix async opening of http files. [Reuben Cummings]

- Be lenient with html parsing. [Reuben Cummings]

- Fix empty xpath and start value bugs. [Reuben Cummings]

v0.33.0 (2016-07-01)
--------------------

Changes
~~~~~~~

- Major refactor for py3 support: [Reuben Cummings]

  - fix py3 and open file errors
  - port missing twisted modules
  - refactor rss parsing
  - and streaming json support
  - rename request function
  - make benchmarks.py a script and add to tests

Bugfixes
~~~~~~~~

- Fix pypy test errors. [Reuben Cummings]

v0.32.0 (2016-06-16)
--------------------

Changes
~~~~~~~

- Refactor to remove Twisted dependency. [Reuben Cummings]

v0.31.0 (2016-06-16)
--------------------

New
~~~

- Add parallel testing. [Reuben Cummings]

v0.30.2 (2016-06-16)
--------------------

Bugfixes
~~~~~~~~

- Add missing optional dependency. [Reuben Cummings]

v0.30.1 (2016-06-16)
--------------------

Bugfixes
~~~~~~~~

- Fix failed test runner. [Reuben Cummings]

- Fix lxml dependency errors. [Reuben Cummings]

v0.30.0 (2016-06-15)
--------------------

New
~~~

- Try loading workflow from curdir first. [Reuben Cummings]

Bugfixes
~~~~~~~~

- Fix remaining pypy errors. [Reuben Cummings]

- Fix “newdict instance” error for pypy. [Reuben Cummings]

- Add detagging to `fetchpage` async parser. [Reuben Cummings]

v0.28.0 (2016-03-25)
--------------------

New
~~~

- Add option to specify value if no regex match found. [Reuben Cummings]

Changes
~~~~~~~

- Make default exchange rate field ‘content’ [Reuben Cummings]

- Split now returns tier of feeds. [Reuben Cummings]

Bugfixes
~~~~~~~~

- Fix test mode for input pipe. [Reuben Cummings]

- Fix terminal parsing. [Reuben Cummings]

- Fix input pipe if no inputs given. [Reuben Cummings]

- Fix sleep config. [Reuben Cummings]

- Fix json bool parsing. [Reuben Cummings]


