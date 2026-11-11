# RPG NeuralMesh: Data Prerequisites and Public Sources

Date: 2026-11-06. What has to be collected or decided before the mesh runs on real knowledge, and which public documents of the group companies can seed the first real catalogues.

## What Must Be Collected or Decided

Nothing is collected today. All four nodes run on invented packs, which stay useful as a test set.

| Step | Who | What it is |
|---|---|---|
| Catalogue of each company | Each subsidiary | A list of catalogue items (for example "materials handling learnings", "inspection records"), each with its owner role and its sharing rule: title only, summary, full text, or live. A decision, not a technical task, and the step that takes longest |
| The documents behind each item | Each subsidiary | Files placed on the company's own node. Each document gets its item, version, date and the topics it is about. A summary is written for items shared as summary-only |
| Group vocabulary | Mesh team with the subsidiaries | The list of topics and skills with their other names. Today 37 topics and 7 skills exist for the synthetic packs. Real companies add their own and confirm the links between them |
| Expert directory | Each subsidiary, each person | Consent recorded per person before they appear, with role and skills, never a name until an introduction is approved |
| Links between companies | The two owners | Each cross-company link (corroborates, conflicts with, fills a gap) approved by both sides in Governance |
| Application vocabularies | Each application team | SkillForge's roles and skills, Snap and Score's assets and conditions, confirmed by each subsidiary. The Snap and Score file of 2026-11-06 is a draft |
| Accounts and roles | IT | Which users belong to which company, and who holds the admin, owner and reviewer roles. Later, corporate sign-in |
| A model and a place to run | IT | A model endpoint the group allows for real data, and one server per node inside each company's network. In development the Claude API is used with synthetic packs |

## Storage

The mesh keeps the extracted text, a keyword index and the vectors of each document, not the file itself. A 200-page annual report is about 500 KB of text, about 1,000 chunks of 600 characters, and about 2 MB of vectors, so about 3 MB in all. One hundred such reports take a few hundred MB. The 19 synthetic packs take about 6 MB. The central graph holds names and links only, in kilobytes. The original files can stay where they are and be linked by reference.

## Public Documents That Can Seed the First Real Catalogues

These are documents the companies publish. They hold no internal knowledge, so they test the pipeline on real text (long PDFs, financial and sustainability wording, product terms) and give each node a first non-synthetic catalogue. They were found by web search on 2026-11-06 and not read in full. Stock exchange archives (NSE, BSE) and the company sites are the reliable download points. Third-party index pages (Screener, Sharpely, sustainabilityreports.com) list the same files by year.

| Company | Document | Where | Catalogue item it could seed | Sharing rule to propose |
|---|---|---|---|---|
| CEAT | Integrated Annual Report FY2025-26 with the Business Responsibility and Sustainability Report, issued with the 67th AGM notice | BSE and NSE filings (scrip 500878, symbol CEATLTD), listed at https://www.screener.in/company/CEATLTD | Corporate: group reporting | Full text (public) |
| CEAT | Investor presentations and call transcripts (May, July, October 2026) | Same listing | Corporate: investor material | Full text (public) |
| KEC International | Integrated Annual Report FY2024-25 (206 pages) and FY2025-26 (dated 29 July 2026) | https://www.sustainabilityreports.com/kec-international/2025/integrated-annual-report and the NSE and BSE filings (scrip 532714) | Corporate: group reporting | Full text (public) |
| KEC International | Business Responsibility and Sustainability Report FY2024-25 (24 pages) and FY2025-26 | https://nsearchives.nseindia.com/corporate/KEC_17072025173341_SEIntimation_BRSR.pdf and https://www.sustainabilityreports.com/kec-international | Corporate: ESG metrics (today the synthetic datapoint F-05) | Full text (public) |
| KEC International | Investor presentation Q1 FY27 (10 August 2026) and Q3 FY26 (30 January 2026) | https://nsearchives.nseindia.com/corporate/KEC_10082026185021_SEintimation_InvestorPPT.pdf and https://bsmedia.business-standard.com/_media/bs/data/announcements/bse/30012026/223365da-541b-4b4b-bc91-3437e0fdd6b3.pdf | Corporate: investor material, order book, project pipeline | Full text (public) |
| Harrisons Malayalam | 49th Annual Report FY2025-26 | https://nsearchives.nseindia.com/corporate/HARRMALAYA_04092026192713_FORUPLOADINGFINALAR2526SD.pdf | Corporate: group reporting, estate and crop overview | Full text (public) |
| Harrisons Malayalam | 48th Annual Report FY2024-25 | https://harrisonsmalayalam.com/download/7566 | Same, previous version (tests SUPERSEDES) | Full text (public) |
| Zensar Technologies | Business Responsibility and Sustainability Report FY2025-26 (filed 8 July 2026) | https://nsearchives.nseindia.com/corporate/ZENSARTECH_08072026161318_Intimation_of_BRSR.pdf | Corporate: ESG and responsible practice | Full text (public) |
| Zensar Technologies | Integrated Annual Report FY2024-25 (195 pages) and FY2025-26 | https://www.sustainabilityreports.com/zensar-technologies and the NSE and BSE filings (symbol ZENSARTECH) | Corporate: group reporting | Full text (public) |
| Zensar Technologies | FY26 results press release | https://www.zensar.com/newsroom/press-releases/zensar-fy26-results-q4-revenue-growth-ai-wins | Commercial: delivery and AI wins (public wording only) | Full text (public) |
| Raychem RPG | Product datasheets and installation instructions for cable accessories | No current official catalogue found by search. The copies found are 2003 to 2007 Tyco Electronics catalogues on third-party sites and one Chemelex datasheet. Ask Raychem RPG for the current catalogue | Engineering: product standards and installation (the Snap and Score inspection domain) | To be set by Raychem RPG |

What these documents do not give: lessons learned, root cause analyses, SOPs, test reports, role profiles and expert directories. Those are internal and come only through the catalogue step above.

## Order of Work

1. Each subsidiary's node loads its public documents from the table as a first real catalogue, with the rule "full text".
2. The group vocabulary is extended with the topics these documents raise (ESG metrics, order book, estate operations, cable accessories), with aliases.
3. The golden questions get five real-document questions beside the synthetic ones, so recall is measured on real text.
4. The catalogue step for internal knowledge starts with one company and one domain, for example CEAT materials handling, where the synthetic pack already shows the shape.

## Sources

Searched on 2026-11-06. Listing pages, not the documents themselves:

- CEAT filings index: https://www.screener.in/company/CEATLTD
- KEC International reports: https://www.sustainabilityreports.com/kec-international
- Harrisons Malayalam annual report FY2025-26: https://nsearchives.nseindia.com/corporate/HARRMALAYA_04092026192713_FORUPLOADINGFINALAR2526SD.pdf
- Zensar Technologies reports: https://www.sustainabilityreports.com/zensar-technologies
- Raychem RPG company listing: https://projectsuppliers.net/en/node/9716
