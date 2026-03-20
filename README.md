# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/Twodragon0/investing/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                  |    Stmts |     Miss |   Cover |   Missing |
|-------------------------------------- | -------: | -------: | ------: | --------: |
| scripts/common/\_\_init\_\_.py        |       17 |        6 |     65% |     30-36 |
| scripts/common/bettafish\_analyzer.py |      646 |      247 |     62% |335-386, 409-453, 497-498, 516-528, 539-540, 542-543, 550-560, 565-575, 578, 630, 634-636, 638-639, 641-642, 646, 650, 833, 836, 839, 880-891, 895-909, 913-926, 930-944, 953, 961-962, 973-983, 990-997, 1033-1039, 1056, 1058, 1060, 1062, 1080-1082, 1088, 1090, 1094, 1160, 1224, 1229, 1263-1268, 1272, 1274, 1278, 1320-1325, 1436, 1477-1547, 1576-1581, 1610, 1620, 1625 |
| scripts/common/browser.py             |      124 |        0 |    100% |           |
| scripts/common/collector\_metrics.py  |       14 |        0 |    100% |           |
| scripts/common/config.py              |       77 |       32 |     58% |10-11, 36-38, 44-46, 56-96, 133-135 |
| scripts/common/crypto\_api.py         |       57 |        0 |    100% |           |
| scripts/common/dedup.py               |      105 |        8 |     92% |65-66, 111-117 |
| scripts/common/enrichment.py          |      517 |       15 |     97% |27, 30-31, 165-166, 177-178, 186-187, 199-200, 262-263, 415-416 |
| scripts/common/entity\_extractor.py   |      106 |        1 |     99% |       180 |
| scripts/common/fmp\_api.py            |      248 |        0 |    100% |           |
| scripts/common/formatters.py          |       30 |        0 |    100% |           |
| scripts/common/image\_generator.py    |     1031 |       50 |     95% |50-54, 64-65, 79-83, 89-92, 296, 416, 447, 452, 729, 1001, 1050-1059, 1070-1073, 1537-1551, 1897, 2181-2186 |
| scripts/common/markdown\_utils.py     |      163 |       29 |     82% |20-56, 316-317 |
| scripts/common/mindspider.py          |      377 |        6 |     98% |603, 673-674, 687-688, 990 |
| scripts/common/post\_generator.py     |      250 |       22 |     91% |330-334, 364, 404, 531, 576, 581, 618-622, 626-628, 666-667, 680-681 |
| scripts/common/rss\_fetcher.py        |      146 |       20 |     86% |23-24, 101-105, 143, 168, 176-177, 185, 190, 195-197, 203, 214, 289-290 |
| scripts/common/signal\_composer.py    |      477 |        2 |     99% |   870-871 |
| scripts/common/summarizer.py          |      802 |       51 |     94% |80, 147, 228, 242, 1147, 1170, 1182-1186, 1223, 1231-1233, 1248, 1264, 1709, 1735, 1741, 1751, 1836, 1844-1853, 1863, 1872, 1877, 1906, 1953, 1955, 1965, 2018, 2072-2078, 2122, 2210-2211, 2341, 2374, 2399-2400, 2404, 2446, 2512, 2640, 2671 |
| scripts/common/translator.py          |      190 |        2 |     99% |  601, 614 |
| scripts/common/utils.py               |      117 |        3 |     97% |     69-71 |
| scripts/common/worldmonitor\_utils.py |        5 |        0 |    100% |           |
| **TOTAL**                             | **5499** |  **494** | **91%** |           |


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