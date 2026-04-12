# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/Twodragon0/investing/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                              |    Stmts |     Miss |   Cover |   Missing |
|-------------------------------------------------- | -------: | -------: | ------: | --------: |
| scripts/backfill\_images.py                       |      313 |      313 |      0% |    10-754 |
| scripts/backfill\_post\_summaries.py              |      831 |      831 |      0% |    3-1215 |
| scripts/check\_description\_quality.py            |      217 |      217 |      0% |     9-461 |
| scripts/check\_jekyll\_build.py                   |       19 |       19 |      0% |      3-28 |
| scripts/check\_recent\_post\_urls.py              |       75 |       75 |      0% |     8-109 |
| scripts/clean\_translation\_cache.py              |       34 |       34 |      0% |     12-58 |
| scripts/collect\_blockchain.py                    |      201 |       27 |     87% |93, 180-181, 254-272, 276, 280-290, 311-313, 334, 358, 369, 381-383, 387 |
| scripts/collect\_coinmarketcap.py                 |      628 |      205 |     67% |42-45, 49-53, 74-98, 106-125, 133-159, 202-208, 224-241, 246-272, 278, 320, 326, 340-346, 353, 358, 368, 383, 388, 392, 446, 536, 599-676, 697, 711, 726-733, 747-748, 812-815, 846-848, 893-896, 911-913, 957-959, 1032-1034, 1040-1042, 1055-1057, 1062-1063, 1127-1128, 1161-1167, 1185, 1258 |
| scripts/collect\_crypto\_news.py                  |      709 |      368 |     48% |51-55, 60-61, 84-110, 121-149, 182-183, 189-209, 215-248, 258-270, 309, 311, 317-358, 363-375, 380-429, 437-440, 445-461, 472, 474, 515-518, 523-531, 550-551, 555, 559-560, 570-607, 670, 690-691, 805-806, 849, 870, 929-932, 935-949, 957-968, 982, 986, 989, 993, 996-1005, 1066, 1127-1139, 1160-1167, 1203, 1233-1397, 1402-1403, 1407 |
| scripts/collect\_defi\_llama.py                   |      428 |      188 |     56% |71-74, 88, 92-97, 116, 122-124, 135-136, 154, 160-161, 177-190, 194-196, 207-220, 224-226, 235-610, 706-709, 800, 827-834, 851-869, 925, 933, 938, 1014-1018, 1022, 1026-1029, 1051-1104, 1117-1118, 1122 |
| scripts/collect\_defi\_yields.py                  |      199 |      199 |      0% |     9-430 |
| scripts/collect\_fmp\_calendar.py                 |      337 |      240 |     29% |55-56, 68-69, 74-92, 97-111, 117, 145-177, 206-209, 227, 236-238, 250, 253, 266-298, 304, 312-345, 357-401, 405, 409-472, 476-574, 579-580, 584 |
| scripts/collect\_geopolitical.py                  |      422 |      351 |     17% |81-156, 161-166, 175-201, 210-270, 279-289, 294-323, 328-343, 348-354, 363, 478, 500-535, 540-576, 586-670, 687-719, 723, 728-731, 735, 739, 743-878, 887-990, 995-996, 1000 |
| scripts/collect\_market\_indicators.py            |      549 |      164 |     70% |62-98, 106-148, 157-173, 178-206, 211-226, 231-246, 251-271, 292-363, 441, 486, 488, 495, 497, 501, 525-526, 539-552, 557-565, 704-709, 826-828, 901, 984-985, 1065-1068, 1110-1111, 1115 |
| scripts/collect\_political\_trades.py             |      375 |       54 |     86% |48-86, 91-152, 157-179, 184-206, 211-228, 274, 320-326, 370-373, 594, 605, 648, 652, 700, 748, 750, 820-840, 849, 880-881, 885 |
| scripts/collect\_regulatory.py                    |      395 |      166 |     58% |163, 195-211, 222-234, 243-272, 284-362, 379-383, 387-388, 393, 510, 544-562, 571, 582, 584, 590-597, 609, 627-633, 643, 719-727, 734, 744-753, 799-802, 836, 840 |
| scripts/collect\_social\_media.py                 |      470 |      365 |     22% |53-57, 76-82, 87, 95, 99, 103, 123-152, 165-170, 182-225, 230-284, 319-366, 383, 387, 392, 423-430, 439-449, 488-985, 990, 994 |
| scripts/collect\_stock\_news.py                   |      465 |      149 |     68% |37-41, 46-47, 65-96, 185-212, 217-262, 286-321, 326-372, 401, 406, 460, 465, 548, 553, 556, 577-582, 591-593, 625-628, 658-659, 664-665, 677, 682-683, 696-697, 700, 703-706, 715-716, 723, 726-727, 731-743, 758-760, 763-766, 813-814, 823-824, 848-849, 915 |
| scripts/collect\_worldmonitor\_news.py            |      415 |       80 |     81% |70, 105, 107, 112, 116-130, 139-152, 164, 167-168, 172-235, 293, 305, 317, 344, 362-460, 482-483, 488-489, 576-579, 584, 604-605, 620-621, 706, 712, 888, 927-928, 1022-1025, 1037-1038, 1084 |
| scripts/common/\_\_init\_\_.py                    |       18 |        6 |     67% |     31-37 |
| scripts/common/base\_collector.py                 |       87 |        0 |    100% |           |
| scripts/common/bettafish\_analyzer.py             |      646 |       58 |     91% |341-347, 357, 359, 361, 416, 425-427, 432-433, 438-439, 445, 449, 451, 578, 630, 887-888, 901-903, 913-926, 932-934, 953, 961-962, 996-997, 1056, 1058, 1060, 1062, 1272, 1278, 1436, 1580-1581, 1610, 1620, 1625 |
| scripts/common/blockchain\_api.py                 |       95 |       10 |     89% |97, 232-242 |
| scripts/common/browser.py                         |      127 |        1 |     99% |       103 |
| scripts/common/collector\_config.py               |       75 |       11 |     85% |26-28, 100-101, 136-138, 156-158 |
| scripts/common/collector\_metrics.py              |       14 |        0 |    100% |           |
| scripts/common/config.py                          |      112 |       57 |     49% |12-13, 26-36, 56-67, 74-76, 80-82, 94-148, 185-187 |
| scripts/common/crypto\_api.py                     |       57 |        0 |    100% |           |
| scripts/common/dedup.py                           |      144 |       10 |     93% |41, 77-78, 112, 130-136 |
| scripts/common/encoding\_guard.py                 |       29 |        0 |    100% |           |
| scripts/common/enrichment.py                      |      674 |       72 |     89% |112-113, 281-286, 298, 302, 309, 312, 365, 382-386, 391, 396-397, 409-423, 429-430, 440-441, 451-452, 478-493, 527, 538-539, 560-561, 593, 653, 801, 837-838, 864, 873, 882, 1365, 1611, 1674, 1680 |
| scripts/common/entity\_extractor.py               |      106 |        1 |     99% |       180 |
| scripts/common/fmp\_api.py                        |      247 |        0 |    100% |           |
| scripts/common/formatters.py                      |       30 |        0 |    100% |           |
| scripts/common/image\_generator/\_\_init\_\_.py   |        6 |        0 |    100% |           |
| scripts/common/image\_generator/base.py           |      320 |       29 |     91% |50-54, 64-65, 79-83, 89-92, 114, 313, 433, 464, 469, 748, 825-826, 881-885 |
| scripts/common/image\_generator/coins.py          |      276 |       24 |     91% |209, 258-267, 278-281, 745-759 |
| scripts/common/image\_generator/market.py         |      287 |        5 |     98% |165, 449-454 |
| scripts/common/image\_generator/news.py           |      146 |        0 |    100% |           |
| scripts/common/image\_generator/og.py             |       59 |        0 |    100% |           |
| scripts/common/markdown\_utils.py                 |      163 |        2 |     99% |     37-38 |
| scripts/common/mindspider.py                      |      377 |        6 |     98% |603, 673-674, 687-688, 990 |
| scripts/common/post\_generator.py                 |      331 |       50 |     85% |214-215, 223-224, 229-241, 282, 287, 293, 403, 440-448, 456-460, 465-470, 500, 540, 619, 622, 706, 752, 757, 847-848, 860-861, 884 |
| scripts/common/rss\_fetcher.py                    |      249 |       12 |     95% |44-45, 80, 91, 178, 187, 272, 281, 292, 302, 330-331 |
| scripts/common/signal\_composer.py                |      477 |        2 |     99% |   870-871 |
| scripts/common/signal\_tracker.py                 |      202 |       12 |     94% |118-123, 199-201, 316-317, 378-379 |
| scripts/common/summarizer.py                      |      867 |       49 |     94% |173, 184, 192-194, 283, 297, 378, 790-792, 1217, 1374, 1376, 1821, 1847, 1853, 1863, 1990, 1998-2007, 2017, 2031, 2061, 2110, 2112, 2122, 2175, 2229-2235, 2279, 2367-2371, 2501, 2532, 2536, 2540, 2561-2562, 2566, 2608, 2674, 2802 |
| scripts/common/translator.py                      |      206 |        8 |     96% |232, 260, 262-263, 303, 305, 705, 718 |
| scripts/common/utils.py                           |      167 |        8 |     95% |159-160, 194-197, 237-239 |
| scripts/common/worldmonitor\_utils.py             |        5 |        0 |    100% |           |
| scripts/continuous\_improvement\_loop.py          |       89 |       89 |      0% |     3-293 |
| scripts/convert\_to\_avif.py                      |       66 |       66 |      0% |     7-123 |
| scripts/enrich\_existing\_posts.py                |      133 |      133 |      0% |    15-311 |
| scripts/fix\_post\_descriptions.py                |      272 |      272 |      0% |    17-572 |
| scripts/generate\_daily\_summary.py               |     1330 |     1330 |      0% |   16-2521 |
| scripts/generate\_market\_summary.py              |      671 |      671 |      0% |   14-1388 |
| scripts/generate\_og\_images.py                   |      828 |      673 |     19% |21-22, 98-99, 116-121, 133-143, 148-158, 163-165, 246-247, 271, 277-345, 361-437, 444-508, 525-656, 665-723, 730-762, 767-856, 866-957, 964-1074, 1090-1180, 1196-1293, 1309-1406, 1422-1482, 1546-1580, 1625-1817, 1821-1831, 1835-2026, 2034-2067, 2079-2128, 2133, 2138, 2143, 2148, 2157-2177, 2181-2274, 2283 |
| scripts/generate\_ops\_10am\_digest.py            |      283 |      205 |     28% |61-71, 75-81, 85-89, 93-116, 120-129, 133-191, 213-214, 217, 225-258, 269-280, 284-292, 296-315, 319-322, 326-329, 341, 343, 347, 349, 351, 388, 406-414, 418-472, 476 |
| scripts/generate\_weekly\_digest.py               |      469 |      328 |     30% |107, 124, 126, 128, 145-147, 152-164, 169-198, 203, 208-220, 229-294, 337, 393-470, 475-483, 488-518, 526-739, 744-774, 778 |
| scripts/improve\_existing\_posts.py               |      448 |      448 |      0% |    13-903 |
| scripts/post\_loop\_to\_slack.py                  |       67 |       67 |      0% |     3-114 |
| scripts/respond\_ai\_mentions.py                  |      259 |      207 |     20% |32-36, 40-67, 71-80, 84-87, 91-124, 128-138, 149-151, 162-164, 175-202, 215-232, 258-259, 274-285, 297-308, 319-336, 340-355, 375-381, 385-482, 486 |
| scripts/smoke\_test\_rendered\_pages.py           |       43 |       43 |      0% |      3-86 |
| scripts/validate\_collector\_summary\_contract.py |       53 |       53 |      0% |      3-95 |
| scripts/verify\_post\_quality.py                  |       78 |       78 |      0% |    13-130 |
| scripts/verify\_rendered\_fixtures.py             |       50 |       50 |      0% |     3-136 |
| scripts/verify\_rendered\_posts.py                |       72 |       51 |     29% |39, 42, 45-46, 56-57, 61-83, 87-117, 121 |
| **TOTAL**                                         | **18892** | **9242** | **51%** |           |


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