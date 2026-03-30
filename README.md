# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/Twodragon0/investing/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                            |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------------ | -------: | -------: | ------: | --------: |
| scripts/common/\_\_init\_\_.py                  |       18 |        6 |     67% |     31-37 |
| scripts/common/base\_collector.py               |       87 |        0 |    100% |           |
| scripts/common/bettafish\_analyzer.py           |      646 |       62 |     90% |345, 347, 357, 359, 361, 425-427, 432-433, 438-439, 445, 449, 451, 578, 630, 881-888, 901-903, 907, 913-926, 932-934, 937-938, 953, 961-962, 996-997, 1056, 1058, 1060, 1062, 1160, 1272, 1274, 1278, 1436, 1580-1581, 1610, 1620, 1625 |
| scripts/common/blockchain\_api.py               |       95 |       10 |     89% |97, 232-242 |
| scripts/common/browser.py                       |      124 |        0 |    100% |           |
| scripts/common/collector\_config.py             |       75 |       11 |     85% |26-28, 100-101, 136-138, 156-158 |
| scripts/common/collector\_metrics.py            |       14 |        0 |    100% |           |
| scripts/common/config.py                        |       82 |       32 |     61% |10-11, 36-38, 44-46, 56-96, 133-135 |
| scripts/common/crypto\_api.py                   |       57 |        0 |    100% |           |
| scripts/common/dedup.py                         |      144 |       10 |     93% |41, 77-78, 112, 130-136 |
| scripts/common/enrichment.py                    |      607 |       52 |     91% |112-113, 155, 158-159, 291, 308-312, 317, 322-323, 334-335, 340-345, 352-353, 363-364, 390-405, 439, 450-451, 501, 561, 699, 735-736, 1251, 1497, 1560 |
| scripts/common/entity\_extractor.py             |      106 |        1 |     99% |       180 |
| scripts/common/fmp\_api.py                      |      247 |        0 |    100% |           |
| scripts/common/formatters.py                    |       30 |        0 |    100% |           |
| scripts/common/image\_generator/\_\_init\_\_.py |        6 |        0 |    100% |           |
| scripts/common/image\_generator/base.py         |      320 |       29 |     91% |50-54, 64-65, 79-83, 89-92, 114, 313, 433, 464, 469, 748, 825-826, 881-885 |
| scripts/common/image\_generator/coins.py        |      276 |       24 |     91% |209, 258-267, 278-281, 745-759 |
| scripts/common/image\_generator/market.py       |      287 |        5 |     98% |165, 449-454 |
| scripts/common/image\_generator/news.py         |      146 |        0 |    100% |           |
| scripts/common/image\_generator/og.py           |       59 |        0 |    100% |           |
| scripts/common/markdown\_utils.py               |      163 |       29 |     82% |20-56, 316-317 |
| scripts/common/mindspider.py                    |      377 |        6 |     98% |603, 673-674, 687-688, 990 |
| scripts/common/post\_generator.py               |      318 |       51 |     84% |214-215, 223-224, 229-241, 382, 419-427, 435-439, 444-449, 479, 519, 598, 601, 680, 726, 731, 768-770, 778, 819-820, 832-833, 856 |
| scripts/common/rss\_fetcher.py                  |      155 |       25 |     84% |24-25, 72-76, 114, 139, 147-148, 156, 161, 166-168, 174, 180-183, 194, 196, 271-272 |
| scripts/common/signal\_composer.py              |      477 |        2 |     99% |   870-871 |
| scripts/common/signal\_tracker.py               |      202 |       13 |     94% |118-123, 199-201, 255, 316-317, 378-379 |
| scripts/common/summarizer.py                    |      816 |       42 |     95% |232, 246, 716-718, 1143, 1237, 1682, 1708, 1714, 1724, 1851, 1859-1868, 1878, 1892, 1921, 1968, 1970, 1980, 2033, 2087-2093, 2137, 2225-2229, 2359, 2388, 2392, 2396, 2417-2418, 2422, 2464, 2530, 2658 |
| scripts/common/translator.py                    |      190 |        2 |     99% |  666, 679 |
| scripts/common/utils.py                         |      118 |        3 |     97% |   101-103 |
| scripts/common/worldmonitor\_utils.py           |        5 |        0 |    100% |           |
| **TOTAL**                                       | **6247** |  **415** | **93%** |           |


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