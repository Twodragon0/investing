# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/Twodragon0/investing/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                  |    Stmts |     Miss |   Cover |   Missing |
|-------------------------------------- | -------: | -------: | ------: | --------: |
| scripts/common/\_\_init\_\_.py        |       17 |        6 |     65% |     30-36 |
| scripts/common/bettafish\_analyzer.py |      646 |       68 |     89% |341-347, 357, 359, 361, 416, 425-427, 432-433, 438-439, 445, 449, 451, 578, 630, 881-888, 901-903, 907, 913-926, 932-934, 937-938, 953, 961-962, 996-997, 1056, 1058, 1060, 1062, 1160, 1272, 1274, 1278, 1436, 1580-1581, 1610, 1620, 1625 |
| scripts/common/blockchain\_api.py     |       95 |       10 |     89% |97, 232-242 |
| scripts/common/browser.py             |      124 |        0 |    100% |           |
| scripts/common/collector\_config.py   |       75 |       11 |     85% |26-28, 100-101, 136-138, 156-158 |
| scripts/common/collector\_metrics.py  |       14 |        0 |    100% |           |
| scripts/common/config.py              |       82 |       32 |     61% |10-11, 36-38, 44-46, 56-96, 133-135 |
| scripts/common/crypto\_api.py         |       57 |        0 |    100% |           |
| scripts/common/dedup.py               |      144 |       10 |     93% |41, 77-78, 112, 130-136 |
| scripts/common/enrichment.py          |      608 |       52 |     91% |112-113, 155, 158-159, 291, 308-312, 317, 322-323, 334-335, 340-345, 352-353, 363-364, 390-405, 451-452, 502, 541, 562, 700, 736-737, 1252, 1498, 1561 |
| scripts/common/entity\_extractor.py   |      106 |        1 |     99% |       180 |
| scripts/common/fmp\_api.py            |      247 |        0 |    100% |           |
| scripts/common/formatters.py          |       30 |        0 |    100% |           |
| scripts/common/image\_generator.py    |     1040 |       52 |     95% |50-54, 64-65, 79-83, 89-92, 296, 416, 447, 452, 731, 806-807, 1017, 1066-1075, 1086-1089, 1553-1567, 1913, 2197-2202 |
| scripts/common/markdown\_utils.py     |      163 |       29 |     82% |20-56, 316-317 |
| scripts/common/mindspider.py          |      377 |        6 |     98% |603, 673-674, 687-688, 990 |
| scripts/common/post\_generator.py     |      318 |       52 |     84% |214-215, 223-224, 229-241, 382, 419-427, 435-439, 444-449, 479, 519, 598, 601, 680, 726, 731, 768-770, 778, 797, 819-820, 832-833, 856 |
| scripts/common/rss\_fetcher.py        |      155 |       25 |     84% |23-24, 101-105, 143, 168, 176-177, 185, 190, 195-197, 203, 209-212, 223, 225, 300-301 |
| scripts/common/signal\_composer.py    |      477 |        2 |     99% |   870-871 |
| scripts/common/signal\_tracker.py     |      202 |       13 |     94% |118-123, 199-201, 255, 316-317, 378-379 |
| scripts/common/summarizer.py          |      819 |       42 |     95% |240, 254, 724-726, 1151, 1245, 1690, 1716, 1722, 1732, 1859, 1867-1876, 1886, 1900, 1929, 1976, 1978, 1988, 2041, 2095-2101, 2145, 2233-2237, 2367, 2396, 2400, 2404, 2425-2426, 2430, 2472, 2538, 2666 |
| scripts/common/translator.py          |      190 |        2 |     99% |  666, 679 |
| scripts/common/utils.py               |      117 |        3 |     97% |     69-71 |
| scripts/common/worldmonitor\_utils.py |        5 |        0 |    100% |           |
| **TOTAL**                             | **6108** |  **416** | **93%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/Twodragon0/investing/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/Twodragon0/investing/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/Twodragon0/investing/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/Twodragon0/investing/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2FTwodragon0%2Finvesting%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/Twodragon0/investing/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.