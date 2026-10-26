# Category mapping list (2026-10-26)

ENG-03, ENG-29 item 1 (review points 4 and 5). Every category label in use on the platform, how many items use it, and how the tree rule resolved it: through its top-level parent in the platform's category tree (the top counts if it is one of the 23, or if the category map points it straight to one of the 23), or why it is unmapped. Nothing is guessed from a label, product or seller name.

Platform database `soco`, read only. Settings config_version 7 (83 category-map entries). Category tree: 344 nodes, 24 top-level. Written by `scripts/category_mapping_report.py`.

## Before and after (26 Oct 2026, dev)

Platform database soco, read only. Engine writes only into the throwaway reco_cat_check (python -m reco.jobs sync, then nightly, on each version; dropped at the end). Before = commit eaa1783; after = the tree rule and the LEGACY_LABEL_MAP path fix. The M1 figures are from the nightly interest job's summary (both methods give the same).

| Measure | Before | After | Note |
|---|---:|---:|---|
| Unmapped labels (daily check) | 140 (355 items) | 33 (70 items) | after: 28 not_in_tree (business types), 5 top_not_mapped (Art & Handicrafts) |
| M1 actions dropped for an unresolved category | 18 | 18 | all 18 are orders, with no post, of 8 products under the top Art & Handicrafts (not one of the 23, not in the category map) |
| Posts with a label outside the 23 (of 550) | 297 | 13 | the 13: Art & Handicrafts sub-categories |
| Posts with no category in the 23 (of 550) | 0 | 0 | the reviewer's 15 (test server) is not reproduced on dev |
| Business follows with no category (of 2,320) | 1917 | 1874 | businessregisters.category holds business types (the industries list), not tree categories |
| Businesses with a category in the 23 (of 60) | 11 | 12 | Home Decor now maps through the tree (Home & Kitchen) |
| M1 score rows written (each method) | 3661 | 3681 | 206 of 208 users scored both times |

## Summary

191 labels in use: **158 mapped**, **33 unmapped** (70 items).

| How mapped | Labels |
|---|---:|
| category map | 4 |
| one of the 23 | 23 |
| tree | 126 |
| tree and category map | 5 |

| Why unmapped | Labels | Items | Meaning |
|---|---:|---:|---|
| not_in_tree | 28 | 48 | no node of this name (or id) in the tree, and no category-map entry |
| top_not_mapped | 5 | 22 | its top is not one of the 23 and the category map has no entry for the top |

## Unmapped labels (for the reviewer)

Left out of category scoring until mapped. Product rows are a category id, shown with its path.

| Label | Used by | Items | Reason | Tree top | Note |
|---|---|---:|---|---|---|
| Art & Handicrafts (category id 6ad23a3a75f362743de1318f) | products 9 | 9 | top_not_mapped | Art & Handicrafts |  |
| Retail | businesses 5 | 5 | not_in_tree |  |  |
| Bronze Idols & Statues | posts 4 | 4 | top_not_mapped | Art & Handicrafts |  |
| Electronics Store | businesses 4 | 4 | not_in_tree |  |  |
| Wooden Handicrafts | posts 4 | 4 | top_not_mapped | Art & Handicrafts |  |
| Agriculture & Seeds | businesses 3 | 3 | not_in_tree |  |  |
| Handicrafts | businesses 3 | 3 | not_in_tree |  |  |
| Jewellery Shop | businesses 3 | 3 | not_in_tree |  |  |
| Manufacturing | businesses 3 | 3 | not_in_tree |  |  |
| Tanjore Paintings | posts 3 | 3 | top_not_mapped | Art & Handicrafts |  |
| Coffee & Tea | businesses 2 | 2 | not_in_tree |  |  |
| Dairy | businesses 2 | 2 | not_in_tree |  |  |
| Footwear & Leather | businesses 2 | 2 | not_in_tree |  |  |
| Handloom Weavers | businesses 2 | 2 | not_in_tree |  |  |
| Pottery & Terracotta | posts 2 | 2 | top_not_mapped | Art & Handicrafts |  |
| Textiles & Sarees | businesses 2 | 2 | not_in_tree |  |  |
| Automobile Accessories | businesses 1 | 1 | not_in_tree |  |  |
| Ayurveda & Siddha | businesses 1 | 1 | not_in_tree |  |  |
| Books & Stationery | businesses 1 | 1 | not_in_tree |  |  |
| Events | businesses 1 | 1 | not_in_tree |  |  |
| Flowers & Gifts | businesses 1 | 1 | not_in_tree |  |  |
| Furniture Store | businesses 1 | 1 | not_in_tree |  |  |
| Hardware & Tools | businesses 1 | 1 | not_in_tree |  |  |
| Kitchenware & Brassware | businesses 1 | 1 | not_in_tree |  |  |
| Mobile Shop | businesses 1 | 1 | not_in_tree |  |  |
| Opticals | businesses 1 | 1 | not_in_tree |  |  |
| Organic Farm | businesses 1 | 1 | not_in_tree |  |  |
| Pet Store | businesses 1 | 1 | not_in_tree |  |  |
| Photography Studio | businesses 1 | 1 | not_in_tree |  |  |
| Printing & Packaging | businesses 1 | 1 | not_in_tree |  |  |
| Spices & Masala | businesses 1 | 1 | not_in_tree |  |  |
| Tailoring & Boutique | businesses 1 | 1 | not_in_tree |  |  |
| Toy Store | businesses 1 | 1 | not_in_tree |  |  |

## Mapped labels with a note

Mapped, but the tree says something the reviewer should see.

| Label | Used by | Items | Category | How | Note |
|---|---|---:|---|---|---|
| Gaming | posts 6, user interests 23 | 29 | Gaming | one of the 23 | one of the 23 by name; the tree puts it under Electronics (Electronics) |

## The tree's top-level nodes

What each top counts as. The app's interestLabel is shown for information only (the rule does not use it); where it differs from the result, the reviewer may want the category map changed.

| Top | Counts as | Reason | App's interestLabel |
|---|---|---|---|
| Appliances | Home & Living |  | Appliances |
| Art & Handicrafts |  | top_not_mapped | Art & Collectibles |
| Automotive | Automotive |  | Automotive |
| Baby Products | Toys & Kids |  |  |
| Bags, Luggage & Travel | Travel & Lifestyle |  | Travel & Lifestyle |
| Beauty & Personal Care | Beauty & Personal Care |  | Beauty & Personal Care |
| Books | Books & Education |  | Books & Education |
| Electronics | Electronics |  | Electronics |
| Fashion | Fashion & Apparel |  | Fashion & Apparel |
| Finance | Finance |  | Finance |
| Food & Grocery | Food & Beverages |  | Food & Beverages |
| Furniture | Home & Living |  |  |
| Garden & Outdoors | Organic & Eco |  |  |
| Health & Household | Health & Wellness |  | Health & Wellness |
| Home & Kitchen | Home & Living |  | Home & Living |
| Jewellery | Jewellery |  | Jewellery |
| Musical Instruments | Music & Entertainment |  | Music & Entertainment |
| Office Products | Office & Business |  | Office & Business |
| Pet Supplies | Pets |  | Pets |
| Sports, Fitness & Outdoors | Sports & Outdoors |  | Sports & Outdoors |
| Tools & Home Improvement | Home & Living |  | Tools & Home Improvement |
| Toys & Games | Toys & Kids |  | Toys & Kids |
| Watches | Jewellery |  | Watches |
| Weddings & Events |  | top_not_mapped | Wedding & Events |

## Below the top: where the app's interestLabel names another of the 23

The rule uses the top only, so everything under these nodes counts in the top's category. The app labels the node itself as another of the 23. Shown for the reviewer; nothing here is applied.

| Node | App's interestLabel | The rule gives | Labels in use beneath it (items) |
|---|---|---|---|
| Electronics > Cameras & Photography | Photography | Electronics | Tripods & Gimbals (4), Action Cameras (3), Mirrorless Cameras (1) |
| Electronics > Computers & Accessories | Technology | Electronics | Laptop Bags (3), Business Laptops (2), External Hard Drives (2), Monitors (1) |
| Electronics > Gaming | Gaming | Electronics | none |
| Fashion > Footwear | Shoes & Footwear | Fashion & Apparel | Sports Shoes (3), Formal Shoes (2), Kids' Footwear (2), Sandals (1), Slippers & Flip-Flops (1) |
| Food & Grocery > Organic & Millets | Organic & Eco | Food & Beverages | Cold-Pressed Oils (3), Millets (3), Organic Staples (2) |

## Every label in use

| Label | Used by | Items | Category | How | Tree top |
|---|---|---:|---|---|---|
| Food & Beverages | posts 118, user interests 79 | 197 | Food & Beverages | one of the 23 |  |
| Fashion & Apparel | posts 57, user interests 77 | 134 | Fashion & Apparel | one of the 23 |  |
| Home & Living | posts 47, user interests 55 | 102 | Home & Living | one of the 23 |  |
| Electronics | posts 31, user interests 61 | 92 | Electronics | one of the 23 | Electronics |
| Beauty & Personal Care | posts 20, user interests 52 | 72 | Beauty & Personal Care | one of the 23 | Beauty & Personal Care |
| Jewellery | posts 21, user interests 45 | 66 | Jewellery | one of the 23 | Jewellery |
| Organic & Eco | posts 35, user interests 30 | 65 | Organic & Eco | one of the 23 |  |
| Food & Grocery (category id 6ad239da75f362743de125cd) | products 62 | 62 | Food & Beverages | tree | Food & Grocery |
| Technology | posts 17, user interests 44 | 61 | Technology | one of the 23 |  |
| Health & Wellness | posts 21, user interests 39 | 60 | Health & Wellness | one of the 23 |  |
| Books & Education | posts 16, user interests 37 | 53 | Books & Education | one of the 23 |  |
| Travel & Lifestyle | posts 20, user interests 33 | 53 | Travel & Lifestyle | one of the 23 |  |
| Art & Collectibles | posts 23, user interests 21 | 44 | Art & Collectibles | one of the 23 |  |
| Automotive | posts 13, user interests 30 | 43 | Automotive | one of the 23 | Automotive |
| Fashion (category id 6ad239b775f362743de12199) | products 43 | 43 | Fashion & Apparel | tree | Fashion |
| Shoes & Footwear | posts 14, user interests 28 | 42 | Shoes & Footwear | one of the 23 |  |
| Sports & Outdoors | posts 15, user interests 27 | 42 | Sports & Outdoors | one of the 23 |  |
| Pets | posts 11, user interests 20 | 31 | Pets | one of the 23 |  |
| Photography | posts 13, user interests 18 | 31 | Photography | one of the 23 |  |
| Gaming | posts 6, user interests 23 | 29 | Gaming | one of the 23 | Electronics |
| Wedding & Events | posts 5, user interests 24 | 29 | Wedding & Events | one of the 23 |  |
| Appliances | posts 6, user interests 22 | 28 | Home & Living | tree and category map | Appliances |
| Toys & Kids | posts 10, user interests 18 | 28 | Toys & Kids | one of the 23 |  |
| Home & Kitchen (category id 6ad239ea75f362743de127c4) | products 27 | 27 | Home & Living | tree | Home & Kitchen |
| Music & Entertainment | posts 10, user interests 16 | 26 | Music & Entertainment | one of the 23 |  |
| Electronics (category id 6ad2397c75f362743de11a61) | products 24 | 24 | Electronics | tree | Electronics |
| Finance | posts 6, user interests 13 | 19 | Finance | one of the 23 | Finance |
| Tools & Home Improvement | posts 3, user interests 14 | 17 | Home & Living | tree and category map | Tools & Home Improvement |
| Watches | posts 6, user interests 11 | 17 | Jewellery | tree and category map | Watches |
| Health & Household (category id 6ad23a0f75f362743de12c44) | products 14 | 14 | Health & Wellness | tree | Health & Household |
| Jewellery (category id 6ad239d175f362743de124c5) | products 14 | 14 | Jewellery | tree | Jewellery |
| Chocolates & Sweets | posts 13 | 13 | Food & Beverages | tree | Food & Grocery |
| Office & Business | posts 6, user interests 6 | 12 | Office & Business | one of the 23 |  |
| Dairy & Eggs | posts 10 | 10 | Food & Beverages | tree | Food & Grocery |
| Art & Handicrafts (category id 6ad23a3a75f362743de1318f) | products 9 | 9 | unmapped | top_not_mapped | Art & Handicrafts |
| Beauty & Personal Care (category id 6ad23a0475f362743de12aee) | products 9 | 9 | Beauty & Personal Care | tree | Beauty & Personal Care |
| Sarees | posts 9 | 9 | Fashion & Apparel | tree | Fashion |
| Pots & Planters | posts 8 | 8 | Organic & Eco | tree | Garden & Outdoors |
| Sports, Fitness & Outdoors (category id 6ad23a1575f362743de12cf6) | products 8 | 8 | Sports & Outdoors | tree | Sports, Fitness & Outdoors |
| Garden & Outdoors (category id 6ad23a3575f362743de130e1) | products 7 | 7 | Organic & Eco | tree | Garden & Outdoors |
| Screen Protectors | posts 7 | 7 | Electronics | tree | Electronics |
| Automotive (category id 6ad23a2775f362743de12f2b) | products 6 | 6 | Automotive | tree | Automotive |
| Educational Toys | posts 6 | 6 | Toys & Kids | tree | Toys & Games |
| Pooja Needs | posts 6 | 6 | Health & Wellness | tree | Health & Household |
| Toys & Games (category id 6ad23a1c75f362743de12dcc) | products 6 | 6 | Toys & Kids | tree | Toys & Games |
| Appliances (category id 6ad239fd75f362743de12a18) | products 5 | 5 | Home & Living | tree | Appliances |
| Books (category id 6ad23a2475f362743de12ec2) | products 5 | 5 | Books & Education | tree | Books |
| Gardening Tools | posts 5 | 5 | Organic & Eco | tree | Garden & Outdoors |
| Girls' Clothing | posts 5 | 5 | Fashion & Apparel | tree | Fashion |
| Helmets | posts 5 | 5 | Automotive | tree | Automotive |
| Indian Classical Instruments | posts 5 | 5 | Music & Entertainment | tree | Musical Instruments |
| Mixer Grinders | posts 5 | 5 | Home & Living | tree | Home & Kitchen |
| Office Products (category id 6ad23a3775f362743de13126) | products 5 | 5 | Office & Business | tree | Office Products |
| Pet Food | posts 5 | 5 | Pets | tree | Pet Supplies |
| Retail | businesses 5 | 5 | unmapped | not_in_tree |  |
| Sunglasses | posts 5 | 5 | Fashion & Apparel | tree | Fashion |
| Tea & Coffee | posts 5 | 5 | Food & Beverages | tree | Food & Grocery |
| Attars | posts 4 | 4 | Beauty & Personal Care | tree | Beauty & Personal Care |
| Brass & Copperware | posts 4 | 4 | Home & Living | tree | Home & Kitchen |
| Bronze Idols & Statues | posts 4 | 4 | unmapped | top_not_mapped | Art & Handicrafts |
| Carpets & Rugs | posts 4 | 4 | Home & Living | tree | Home & Kitchen |
| Chargers | posts 4 | 4 | Electronics | tree | Electronics |
| Cycling | posts 4 | 4 | Sports & Outdoors | tree | Sports, Fitness & Outdoors |
| Electronics Store | businesses 4 | 4 | unmapped | not_in_tree |  |
| Fruits & Vegetables | posts 4 | 4 | Food & Beverages | tree | Food & Grocery |
| Home Office Chairs | posts 4 | 4 | Home & Living | tree | Furniture |
| Kurtas & Kurtis | posts 4 | 4 | Fashion & Apparel | tree | Fashion |
| Musical Instruments (category id 6ad23a3275f362743de13078) | products 4 | 4 | Music & Entertainment | tree | Musical Instruments |
| Pet Supplies (category id 6ad23a2a75f362743de12f94) | products 4 | 4 | Pets | tree | Pet Supplies |
| Ready Meals | posts 4 | 4 | Food & Beverages | tree | Food & Grocery |
| Siddha & Herbal | posts 4 | 4 | Health & Wellness | tree | Health & Household |
| Tools & Home Improvement (category id 6ad23a2e75f362743de12ffd) | products 4 | 4 | Home & Living | tree | Tools & Home Improvement |
| Tripods & Gimbals | posts 4 | 4 | Electronics | tree | Electronics |
| Trousers | posts 4 | 4 | Fashion & Apparel | tree | Fashion |
| Watches (category id 6ad2399d75f362743de11e7f) | products 4 | 4 | Jewellery | tree | Watches |
| Wooden Handicrafts | posts 4 | 4 | unmapped | top_not_mapped | Art & Handicrafts |
| Action Cameras | posts 3 | 3 | Electronics | tree | Electronics |
| Agriculture & Seeds | businesses 3 | 3 | unmapped | not_in_tree |  |
| Bakery & Sweets | businesses 3 | 3 | Food & Beverages | category map |  |
| Bath & Body | posts 3 | 3 | Beauty & Personal Care | tree | Beauty & Personal Care |
| Beverages | posts 3 | 3 | Food & Beverages | tree | Food & Grocery |
| Blankets & Quilts | posts 3 | 3 | Home & Living | tree | Home & Kitchen |
| Children's Books | posts 3 | 3 | Books & Education | tree | Books |
| Cold-Pressed Oils | posts 3 | 3 | Food & Beverages | tree | Food & Grocery |
| Furniture (category id 6ad239a775f362743de11fb1) | products 3 | 3 | Home & Living | tree | Furniture |
| Gold & Silver Coins | posts 3 | 3 | Jewellery | tree | Jewellery |
| Grocery & Supermarket | businesses 3 | 3 | Food & Beverages | category map |  |
| Handicrafts | businesses 3 | 3 | unmapped | not_in_tree |  |
| Home Decor | businesses 1, posts 2 | 3 | Home & Living | tree | Home & Kitchen |
| Innerwear | posts 3 | 3 | Fashion & Apparel | tree | Fashion |
| Jeans | posts 3 | 3 | Fashion & Apparel | tree | Fashion |
| Jewellery Shop | businesses 3 | 3 | unmapped | not_in_tree |  |
| Laptop Bags | posts 3 | 3 | Electronics | tree | Electronics |
| Manufacturing | businesses 3 | 3 | unmapped | not_in_tree |  |
| Millets | posts 3 | 3 | Food & Beverages | tree | Food & Grocery |
| Notebooks & Diaries | posts 3 | 3 | Office & Business | tree | Office Products |
| Pickles | posts 3 | 3 | Food & Beverages | tree | Food & Grocery |
| Power Banks | posts 3 | 3 | Electronics | tree | Electronics |
| Restaurant | businesses 3 | 3 | Food & Beverages | category map |  |
| Spices | posts 3 | 3 | Food & Beverages | tree | Food & Grocery |
| Sports Shoes | posts 3 | 3 | Fashion & Apparel | tree | Fashion |
| Tanjore Paintings | posts 3 | 3 | unmapped | top_not_mapped | Art & Handicrafts |
| Anklets | posts 2 | 2 | Jewellery | tree | Jewellery |
| Ayurveda | posts 2 | 2 | Health & Wellness | tree | Health & Household |
| Bakery | posts 2 | 2 | Food & Beverages | tree | Food & Grocery |
| Boys' Clothing | posts 2 | 2 | Fashion & Apparel | tree | Fashion |
| Business Laptops | posts 2 | 2 | Electronics | tree | Electronics |
| Coffee & Tea | businesses 2 | 2 | unmapped | not_in_tree |  |
| Coffee Makers | posts 2 | 2 | Home & Living | tree | Home & Kitchen |
| Comics | posts 2 | 2 | Books & Education | tree | Books |
| Cricket | posts 2 | 2 | Sports & Outdoors | tree and category map | Sports, Fitness & Outdoors |
| Dairy | businesses 2 | 2 | unmapped | not_in_tree |  |
| Dinnerware | posts 2 | 2 | Home & Living | tree | Home & Kitchen |
| Electrical | posts 2 | 2 | Home & Living | tree | Tools & Home Improvement |
| Exam Preparation | posts 2 | 2 | Books & Education | tree | Books |
| External Hard Drives | posts 2 | 2 | Electronics | tree | Electronics |
| First Aid | posts 2 | 2 | Health & Wellness | tree | Health & Household |
| Footwear & Leather | businesses 2 | 2 | unmapped | not_in_tree |  |
| Formal Shoes | posts 2 | 2 | Fashion & Apparel | tree | Fashion |
| Handloom Weavers | businesses 2 | 2 | unmapped | not_in_tree |  |
| Kids' Footwear | posts 2 | 2 | Fashion & Apparel | tree | Fashion |
| Non-Fiction | posts 2 | 2 | Books & Education | tree | Books |
| Organic Staples | posts 2 | 2 | Food & Beverages | tree | Food & Grocery |
| Perfumes | posts 2 | 2 | Beauty & Personal Care | tree | Beauty & Personal Care |
| Pottery & Terracotta | posts 2 | 2 | unmapped | top_not_mapped | Art & Handicrafts |
| Silver Jewellery | posts 2 | 2 | Jewellery | tree | Jewellery |
| Skin Care | posts 2 | 2 | Beauty & Personal Care | tree | Beauty & Personal Care |
| Smartphones | posts 2 | 2 | Electronics | tree | Electronics |
| Snacks | posts 2 | 2 | Food & Beverages | tree | Food & Grocery |
| Sugar, Salt & Jaggery | posts 2 | 2 | Food & Beverages | tree | Food & Grocery |
| Textiles & Sarees | businesses 2 | 2 | unmapped | not_in_tree |  |
| True Wireless Earbuds | posts 2 | 2 | Electronics | tree | Electronics |
| Yoga Mats | posts 2 | 2 | Sports & Outdoors | tree | Sports, Fitness & Outdoors |
| Air Coolers | posts 1 | 1 | Home & Living | tree | Appliances |
| Analog Watches | posts 1 | 1 | Jewellery | tree | Watches |
| Art & Craft Supplies | posts 1 | 1 | Office & Business | tree | Office Products |
| Automobile Accessories | businesses 1 | 1 | unmapped | not_in_tree |  |
| Ayurveda & Siddha | businesses 1 | 1 | unmapped | not_in_tree |  |
| Bangles & Bracelets | posts 1 | 1 | Jewellery | tree | Jewellery |
| Bedsheets | posts 1 | 1 | Home & Living | tree | Home & Kitchen |
| Belts | posts 1 | 1 | Fashion & Apparel | tree | Fashion |
| Board Games | posts 1 | 1 | Toys & Kids | tree | Toys & Games |
| Books & Stationery | businesses 1 | 1 | unmapped | not_in_tree |  |
| Car Accessories | posts 1 | 1 | Automotive | tree | Automotive |
| Car Care | posts 1 | 1 | Automotive | tree | Automotive |
| Dals & Pulses | posts 1 | 1 | Food & Beverages | tree | Food & Grocery |
| Dog Supplies | posts 1 | 1 | Pets | tree | Pet Supplies |
| Earrings | posts 1 | 1 | Jewellery | tree | Jewellery |
| Ethnic Sets | posts 1 | 1 | Fashion & Apparel | tree | Fashion |
| Events | businesses 1 | 1 | unmapped | not_in_tree |  |
| Fans | posts 1 | 1 | Home & Living | tree | Appliances |
| Flowers & Gifts | businesses 1 | 1 | unmapped | not_in_tree |  |
| Furniture Store | businesses 1 | 1 | unmapped | not_in_tree |  |
| Gold Jewellery | posts 1 | 1 | Jewellery | tree | Jewellery |
| Hardware & Tools | businesses 1 | 1 | unmapped | not_in_tree |  |
| Jewellery Sets | posts 1 | 1 | Jewellery | tree | Jewellery |
| Keyboards & Pianos | posts 1 | 1 | Music & Entertainment | tree | Musical Instruments |
| Kitchenware & Brassware | businesses 1 | 1 | unmapped | not_in_tree |  |
| Kurtas | posts 1 | 1 | Fashion & Apparel | tree | Fashion |
| Lamps | posts 1 | 1 | Home & Living | tree | Home & Kitchen |
| Mirrorless Cameras | posts 1 | 1 | Electronics | tree | Electronics |
| Mobile Shop | businesses 1 | 1 | unmapped | not_in_tree |  |
| Monitors | posts 1 | 1 | Electronics | tree | Electronics |
| Musical Instruments | businesses 1 | 1 | Music & Entertainment | tree and category map | Musical Instruments |
| Opticals | businesses 1 | 1 | unmapped | not_in_tree |  |
| Organic Farm | businesses 1 | 1 | unmapped | not_in_tree |  |
| Pet Grooming | posts 1 | 1 | Pets | tree | Pet Supplies |
| Pet Store | businesses 1 | 1 | unmapped | not_in_tree |  |
| Pharmacy | businesses 1 | 1 | Health & Wellness | category map |  |
| Photography Studio | businesses 1 | 1 | unmapped | not_in_tree |  |
| Plants & Seeds | posts 1 | 1 | Organic & Eco | tree | Garden & Outdoors |
| Power Tools | posts 1 | 1 | Home & Living | tree | Tools & Home Improvement |
| Printing & Packaging | businesses 1 | 1 | unmapped | not_in_tree |  |
| Refrigerators | posts 1 | 1 | Home & Living | tree | Appliances |
| Remote Control Toys | posts 1 | 1 | Toys & Kids | tree | Toys & Games |
| Rice | posts 1 | 1 | Food & Beverages | tree | Food & Grocery |
| Rings | posts 1 | 1 | Jewellery | tree | Jewellery |
| Salwar Suits | posts 1 | 1 | Fashion & Apparel | tree | Fashion |
| Sandals | posts 1 | 1 | Fashion & Apparel | tree | Fashion |
| School Supplies | posts 1 | 1 | Office & Business | tree | Office Products |
| Shirts | posts 1 | 1 | Fashion & Apparel | tree | Fashion |
| Slippers & Flip-Flops | posts 1 | 1 | Fashion & Apparel | tree | Fashion |
| Smart TVs | posts 1 | 1 | Electronics | tree | Electronics |
| Soundbars | posts 1 | 1 | Electronics | tree | Electronics |
| Spices & Masala | businesses 1 | 1 | unmapped | not_in_tree |  |
| Swings | posts 1 | 1 | Home & Living | tree | Furniture |
| T-Shirts | posts 1 | 1 | Fashion & Apparel | tree | Fashion |
| Tailoring & Boutique | businesses 1 | 1 | unmapped | not_in_tree |  |
| Toy Store | businesses 1 | 1 | unmapped | not_in_tree |  |
| Wall Decor | posts 1 | 1 | Home & Living | tree | Home & Kitchen |
| Washing Machines | posts 1 | 1 | Home & Living | tree | Appliances |

## Decisions where the rule is silent (26 Oct 2026)

1. A label that is itself one of the 23 (case and spacing ignored) is that category: ENG-03 matches a post's categories to the 23 by name, and the Build List comes first. Where the tree puts a node of that name under another top, it is noted below and not applied.
2. Names are found in the tree ignoring case and spacing, the same key as matching the 23. Ids (products) are found by id.
3. The top is found by following parent links (the actual parent), not the node's path. A node with no parent is a top only at level 0 (or no level); a missing parent or a loop is no_parent.
4. The top counts only by its own name: one of the 23, or a category-map entry for the top that points to one of the 23. A top with no map entry is top_not_mapped (the rule's 'otherwise unmapped').
5. Two or more nodes with one name: mapped only if every one resolves, and all to the same category; otherwise ambiguous (the label cannot say which node it means).
6. The direct rule stays for a label's own category-map entry. Tree and map both give a category and they differ: ambiguous, neither picked. Only one gives a category: it is used (noted where the tree's top was not mapped). A label's own map entry that does not point to one of the 23: map_not_to_23, whatever the tree says.
7. A product's category id (categoryPathIds[0], else basicInfo.categoryId) is followed up its parents to its top; an id is never ambiguous and takes no direct rule.
8. The app's interestLabel on category nodes is shown for information only; the rule does not use it.
9. The tree is read at most once a minute per process (the settings' reload interval).
