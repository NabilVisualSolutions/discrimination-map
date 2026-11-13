# Open RSS/Atom feeds

Tested from this machine on **2026-10-21** with `User-Agent: dxmap-agent (+https://map.nabilvs.com)`, following redirects, honouring robots.txt (the check below is the same code the agent runs). "Items" is the number of entries in the feed at the time, "newest" the age of the newest one, "incident items" how many of them the incident filter kept in that single snapshot (a 7 day window, so most feeds show 0 most days; that is expected, the filter is strict on purpose).

**Licence / terms column.** The text is what the feed's own `<copyright>` element said, verbatim, or `none in feed`. I did **not** read each publisher's terms of use page. Where it says `unknown` nothing was verified. Nothing is copied beyond headline, link, publisher name, date and a snippet of at most 160 characters; that is a design limit, not a legal opinion. Feeds whose own text restricts them to personal / non-commercial use were **not** added (Le Monde, NRC, NPR).

## Feeds in `backend/feeds.json` (40)

| Feed | Publisher | Region | Lang | HTTP | Format | Items | Newest | Incident items | robots.txt | Licence / terms |
|---|---|---|---|---|---|---|---|---|---|---|
| https://www.amadeu-antonio-stiftung.de/feed/ | Amadeu Antonio Stiftung | Germany | de | 200 | RSS/Atom | 30 | 2026-10-12 | 0 | allowed | none in feed (unknown) |
| https://www.belltower.news/feed/ | Belltower.News | Germany | de | 200 | RSS/Atom | 10 | 2026-10-20 | 0 | allowed | none in feed (unknown) |
| https://verband-brg.de/feed/ | VBRG e.V. | Germany | de | 200 | RSS/Atom | 10 | 2026-09-09 | 0 | allowed | none in feed (unknown) |
| https://www.endstation-rechts.de/rss.xml | Endstation Rechts. | Germany | de | 200 | RSS/Atom | 20 | 2026-10-09 | 0 | allowed | none in feed (unknown) |
| https://rechtsaussen.berlin/feed/ | Berlin rechtsaußen | Germany | de | 200 | RSS/Atom | 10 | 2026-09-25 | 0 | allowed | none in feed (unknown) |
| https://www.tagesschau.de/inland/index~rss2.xml | tagesschau.de (ARD) | Germany | de | 200 | RSS/Atom | 49 | 2026-10-21 | 1 | allowed | ARD-aktuell / tagesschau.de |
| https://tellmamauk.org/feed/ | Tell MAMA | United Kingdom | en | 200 | RSS/Atom | 100 | 2026-10-20 | 1 | allowed | none in feed (unknown) |
| https://www.stophateuk.org/feed/ | Stop Hate UK | United Kingdom | en | 200 | RSS/Atom | 10 | 2026-10-08 | 0 | allowed | none in feed (unknown) |
| https://searchlightmagazine.com/feed/ | Searchlight Magazine | United Kingdom | en | 200 | RSS/Atom | 10 | 2026-10-20 | 0 | allowed | none in feed (unknown) |
| https://www.theguardian.com/world/race/rss | The Guardian | United Kingdom | en | 200 | RSS/Atom | 20 | 2026-10-20 | 1 | allowed | Guardian News & Media Limited or its affiliated companies. All rights reserved. 2026 |
| https://www.theguardian.com/world/far-right/rss | The Guardian | United Kingdom | en | 200 | RSS/Atom | 20 | 2026-10-21 | 0 | allowed | Guardian News & Media Limited or its affiliated companies. All rights reserved. 2026 |
| https://feeds.bbci.co.uk/news/uk/rss.xml | BBC News | United Kingdom | en | 200 | RSS/Atom | 27 | 2026-10-21 | 1 | allowed | Copyright: (C) British Broadcasting Corporation, see https://www.bbc.co.uk/usingthebbc/terms-of-use/#15metadataandrssfeeds for terms and con |
| https://www.adl.org/rss.xml | ADL | United States | en | 200 | RSS/Atom | 10 | 2026-10-20 | 0 | allowed | none in feed (unknown) |
| https://www.cair.com/feed/ | CAIR | United States | en | 200 | RSS/Atom | 10 | 2026-10-21 | 2 | allowed | none in feed (unknown) |
| https://www.theguardian.com/us-news/rss | The Guardian | United States | en | 200 | RSS/Atom | 33 | 2026-10-21 | 0 | allowed | Guardian News and Media Limited or its affiliated companies. All rights reserved. 2026 |
| https://fra.europa.eu/en/rss.xml | EU Agency for Fundamental Rights (FRA) | Europe | en | 200 | RSS/Atom | 10 | 2026-10-19 | 0 | allowed | none in feed (unknown) |
| https://www.enar-eu.org/feed/ | European Network Against Racism (ENAR) | Europe | en | 200 | RSS/Atom | 10 | 2026-10-08 | 0 | allowed | none in feed (unknown) |
| https://www.ilga-europe.org/feed/ | ILGA-Europe | Europe | en | 200 | RSS/Atom | 10 | 2026-10-14 | 0 | allowed | none in feed (unknown) |
| https://rss.dw.com/xml/rss-en-all | Deutsche Welle | International | en | 200 | RSS/Atom | 135 | 2026-10-21 | 0 | allowed | 2026 DW |
| https://www.licra.org/feed | LICRA | France | fr | 200 | RSS/Atom | 10 | 2026-10-20 | 0 | allowed | none in feed (unknown) |
| https://www.rfi.fr/fr/france/rss | RFI | France | fr | 200 | RSS/Atom | 30 | 2026-10-21 | 0 | allowed | none in feed (unknown) |
| https://www.liberation.fr/arc/outboundfeeds/rss-all/collection/accueil-une/?outputType=xml | Libération | France | fr | 200 | RSS/Atom | 20 | 2026-10-21 | 0 | allowed | none in feed (unknown) |
| https://www.eldiario.es/rss/ | elDiario.es | Spain | es | 200 | RSS/Atom | 124 | 2026-10-21 | 0 | allowed | Copyright eldiario.es |
| https://www.ansa.it/sito/notizie/cronaca/cronaca_rss.xml | ANSA | Italy | it | 200 | RSS/Atom | 159 | 2026-10-21 | 0 | allowed | Copyright: (C) ANSA, https://www.ansa.it/sito/static/disclaimer.html |
| https://www.repubblica.it/rss/cronaca/rss2.0.xml | la Repubblica | Italy | it | 200 | RSS/Atom | 25 | 2026-10-21 | 0 | allowed | Copyright 2026 - Gruppo Editoriale l'Espresso |
| https://feeds.nos.nl/nosnieuwsbinnenland | NOS | Netherlands | nl | 200 | RSS/Atom | 20 | 2026-10-21 | 0 | allowed | Copyright NOS |
| https://www.svt.se/rss.xml | SVT Nyheter | Sweden | sv | 200 | RSS/Atom | 100 | 2026-10-21 | 0 | allowed | © Sveriges Television AB |
| https://www.nrk.no/toppsaker.rss | NRK | Norway | no | 200 | RSS/Atom | 98 | 2026-10-21 | 0 | allowed | none in feed (unknown) |
| https://allafrica.com/tools/headlines/rdf/latest/headlines.rdf | allAfrica | Africa | en | 200 | RSS/Atom | 33 | 2026-10-21 | 0 | allowed | none in feed (unknown) |
| https://www.dailymaverick.co.za/dmrss/ | Daily Maverick | South Africa | en | 200 | RSS/Atom | 50 | 2026-10-21 | 0 | allowed | none in feed (unknown) |
| https://www.nation.africa/kenya/rss.xml | Nation (Kenya) | Kenya | en | 200 | RSS/Atom | 25 | 2026-10-21 | 0 | allowed | none in feed (unknown) |
| https://www.thehindu.com/news/national/feeder/default.rss | The Hindu | India | en | 200 | RSS/Atom | 60 | 2026-10-21 | 0 | allowed | Copyright (C) 2026 THG PUBLISHING PVT LTD. |
| https://www.dawn.com/feeds/home | Dawn | Pakistan | en | 200 | RSS/Atom | 25 | 2026-10-21 | 0 | allowed | Copyright 2026 |
| https://bianet.org/rss/english | bianet | Turkey | en | 200 | RSS/Atom | 50 | 2026-10-21 | 0 | allowed | none in feed (unknown) |
| https://feeds.bbci.co.uk/mundo/rss.xml | BBC Mundo | International | es | 200 | RSS/Atom | 34 | 2026-10-21 | 0 | allowed | Derechos Reservados de la British Broadcasting Corporation (Corporación Británica de Radiodifusión) |
| https://feeds.folha.uol.com.br/cotidiano/rss091.xml | Folha de S.Paulo | Brazil | pt | 200 | RSS/Atom | 100 | 2026-10-21 | 0 | allowed | Copyright Folha de S.Paulo. Todos os direitos reservados. |
| https://www.aljazeera.com/xml/rss/all.xml | Al Jazeera | International | en | 200 | RSS/Atom | 25 | 2026-10-21 | 0 | allowed | © 2026 Al Jazeera Media Network |
| https://www.middleeasteye.net/rss | Middle East Eye | Middle East | en | 200 | RSS/Atom | 20 | 2026-10-21 | 0 | allowed | none in feed (unknown) |
| https://www.jta.org/feed | Jewish Telegraphic Agency | International | en | 200 | RSS/Atom | 20 | 2026-10-21 | 0 | allowed | none in feed (unknown) |
| https://www.abc.net.au/news/feed/45910/rss.xml | ABC News (Australia) | Australia | en | 200 | RSS/Atom | 25 | 2026-10-21 | 0 | allowed | Copyright 2026, Australian Broadcasting Corporation. All Rights Reserved. |

## Tested and not used

Valid feed but not added: too many near-duplicates of a feed already in the list (e.g. the other BBC and Guardian regional feeds, DW and France24 language editions), stale (newest item older than about 60 days), empty, or terms restrict use.

| Feed | Region | HTTP | Result | Why not used |
|---|---|---|---|---|
| https://www.thenationalnews.com/rss | UAE | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://feeds.bbci.co.uk/news/world/africa/rss.xml | Africa | 200 | valid, 34 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.theguardian.com/world/africa/rss | Africa | 200 | valid, 20 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.clarin.com/rss/lo-ultimo/ | Argentina | 200 | valid, 10 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.pagina12.com.ar/rss/portada | Argentina | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://feeds.bbci.co.uk/news/world/asia/rss.xml | Asia | 200 | valid, 17 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.theguardian.com/world/asia-pacific/rss | Asia | 200 | valid, 20 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.orf.at/rss | Austria | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://rss.orf.at/news.xml | Austria | 200 | valid, 25 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.derstandard.at/rss | Austria | 200 | valid, 156 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.abc.net.au/news/feed/51120/rss.xml | Australia | 200 | valid, 25 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.theguardian.com/australia-news/rss | Australia | 200 | valid, 19 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.sbs.com.au/news/feed | Australia | 200 | valid, 25 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.thedailystar.net/frontpage/rss.xml | Bangladesh | 200 | valid, 10 items | stale, newest item 1552 days old |
| https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml | Brazil | 200 | valid, 10 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.folha.uol.com.br/rss/ | Brazil | 200 | not a feed | returned HTML or an error page, not RSS/Atom (not XML: syntax error: line 4, column 0) |
| https://g1.globo.com/rss/g1/ | Brazil | 200 | valid, 100 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.cbc.ca/webfeed/rss/rss-canada | Canada | - | no response (ReadTimeout) | could not connect from this machine |
| https://www.cbc.ca/webfeed/rss/rss-world | Canada | - | no response (ReadTimeout) | could not connect from this machine |
| https://www.srf.ch/news/bnf/rss/1646 | Switzerland | 200 | valid, 82 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.swissinfo.ch/eng/rss/ | Switzerland | 410 | HTTP 410 | URL does not exist (guessed address) |
| https://www.humanrights.ch/en/rss | Switzerland | 429 | HTTP 429 | server busy or rate limited when tested |
| https://www.eltiempo.com/rss/colombia.xml | Colombia | 200 | valid, 10 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.antifa-infoblatt.de/feed | Germany | - | no response (ConnectError) | could not connect from this machine |
| https://www.belltower.news/rss.xml | Germany | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://chronik.lsa-sachsen-anhalt.de/feed | Germany | - | no response (ConnectError) | could not connect from this machine |
| https://rss.dw.com/rdf/rss-de-all | Germany | 200 | valid, 72 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://rss.dw.com/rdf/rss-de-top | Germany | 200 | valid, 14 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.endstation-rechts.de/feed | Germany | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://www.theguardian.com/world/germany/rss | Germany | 200 | valid, 20 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.mobile-beratung-gegen-rechtsextremismus.de/feed/ | Germany | - | no response (ConnectError) | could not connect from this machine |
| https://www.mbr-berlin.de/feed/ | Germany | 200 | valid, 10 items | stale, newest item 72 days old |
| https://www.mut-gegen-rechte-gewalt.de/rss.xml | Germany | - | no response (ConnectError) | could not connect from this machine |
| https://www.mut-gegen-rechte-gewalt.de/feed | Germany | - | no response (ConnectError) | could not connect from this machine |
| https://www.opferperspektive.de/feed | Germany | - | no response (ConnectError) | could not connect from this machine |
| https://www.reachoutberlin.de/feed | Germany | 502 | HTTP 502 | server busy or rate limited when tested |
| https://www.reachoutberlin.de/de/rss.xml | Germany | 502 | HTTP 502 | server busy or rate limited when tested |
| https://www.sueddeutsche.de/rss/Politik | Germany | 200 | not a feed | returned HTML or an error page, not RSS/Atom (feed too large) |
| https://www.spiegel.de/panorama/index.rss | Germany | 200 | valid, 20 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.spiegel.de/politik/index.rss | Germany | 200 | valid, 20 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.tagesschau.de/xml/rss2/ | Germany | 200 | valid, 40 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://verband-brg.de/feed/ | Germany | 200 | valid, 10 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.verband-brg.de/feed | Germany | 200 | valid, 10 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.zeit.de/gesellschaft/index | Germany | 403 | HTTP 403 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://newsfeed.zeit.de/index | Germany | 200 | valid, 15 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.zeit.de/politik/index | Germany | 403 | HTTP 403 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://www.apabiz.de/feed/ | Germany | 200 | valid, 10 items | stale, newest item 76 days old |
| https://www.apabiz.de/rss | Germany | 200 | valid, 10 items | stale, newest item 76 days old |
| https://taz.de/!p4608;rss/ | Germany | 200 | valid, 50 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.dr.dk/nyheder/service/feeds/allenyheder | Denmark | 200 | valid, 20 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://e00-elmundo.uecdn.es/elmundo/rss/portada.xml | Spain | 200 | valid, 26 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://elpais.com/rss/elpais/portada.xml | Spain | 200 | valid, 21 items | stale, newest item 2425 days old |
| https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada | Spain | 200 | valid, 151 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.theguardian.com/world/spain/rss | Spain | 200 | valid, 20 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.movimientocontralaintolerancia.com/feed | Spain | - | no response (ConnectTimeout) | could not connect from this machine |
| https://www.rtve.es/api/noticias.rss | Spain | 200 | not a feed | returned HTML or an error page, not RSS/Atom (not XML: not well-formed (invalid token)) |
| https://feeds.bbci.co.uk/news/world/europe/rss.xml | Europe | 200 | valid, 21 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.coe.int/en/web/portal/rss | Europe | 403 | HTTP 403 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://ecre.org/feed/ | Europe | 200 | valid, 10 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.coe.int/en/web/european-commission-against-racism-and-intolerance/rss | Europe | 403 | HTTP 403 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://www.enar-eu.org/rss.xml | Europe | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://www.euractiv.com/feed/ | Europe | 503 | HTTP 503 | server busy or rate limited when tested |
| https://www.euronews.com/rss | Europe | 200 | valid, 50 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://fra.europa.eu/en/news/rss | Europe | 200 | not a feed | returned HTML or an error page, not RSS/Atom (not XML: mismatched tag: line 81, column) |
| https://www.theguardian.com/world/europe-news/rss | Europe | 200 | valid, 19 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.osce.org/odihr/rss | Europe | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://hatecrime.osce.org/rss.xml | Europe | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://www.osce.org/rss.xml | Europe | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://yle.fi/rss/uutiset/paauutiset | Finland | 200 | valid, 12 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://yle.fi/rss/t/18-34953/en | Finland | 200 | valid, 20 items | stale, newest item 1342 days old |
| https://www.20minutes.fr/feeds/rss-une.xml | France | 200 | valid, 30 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.theguardian.com/world/france/rss | France | 200 | valid, 20 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.ladepeche.fr/rss.xml | France | 200 | valid, 100 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.lemonde.fr/racisme/rss_full.xml | France | 200 | valid, 20 items | feed text restricts to personal / non-commercial use |
| https://www.lemonde.fr/societe/rss_full.xml | France | 200 | valid, 20 items | feed text restricts to personal / non-commercial use |
| https://www.lemonde.fr/rss/une.xml | France | 200 | valid, 16 items | feed text restricts to personal / non-commercial use |
| https://www.mrap.fr/feed | France | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://www.sos-racisme.org/feed/ | France | 200 | valid, 0 items | feed has no items |
| https://sos-racisme.org/feed/ | France | 200 | valid, 0 items | feed has no items |
| https://www.scmp.com/rss/91/feed | Hong Kong | 200 | valid, 50 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.irishtimes.com/cmlink/news-1.1319192 | Ireland | 200 | valid, 20 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.rte.ie/news/rss/news-headlines.xml | Ireland | 200 | valid, 20 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.thejournal.ie/feed/ | Ireland | 403 | HTTP 403 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://www.haaretz.com/srv/haaretz-latest-headlines | Israel | 200 | valid, 100 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.jpost.com/rss/rssfeedsheadlines.aspx | Israel | 200 | valid, 30 items | stale, newest item 492 days old |
| https://www.timesofisrael.com/feed/ | Israel | 200 | valid, 13 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.antisemitism.org.il/rss | Israel | - | no response (ConnectError) | could not connect from this machine |
| https://indianexpress.com/section/india/feed/ | India | 200 | valid, 200 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://scroll.in/feed | India | 200 | not a feed | returned HTML or an error page, not RSS/Atom (not XML: not well-formed (invalid token)) |
| https://www.thehindu.com/news/international/feeder/default.rss | India | 200 | valid, 60 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.aljazeera.net/aljazeerarss/a7c186be-1baa-4bd4-9d80-a84db769f779/73d0e1b4-532f-45ef-b135-bfdff8b8cab9 | International | 200 | valid, 25 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.amnesty.org/en/latest/news/feed/ | International | 403 | HTTP 403 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://www.amnesty.org/en/feed/ | International | 403 | HTTP 403 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://feeds.bbci.co.uk/arabic/rss.xml | International | 200 | valid, 25 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://feeds.bbci.co.uk/portuguese/rss.xml | International | 200 | valid, 27 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://feeds.bbci.co.uk/hindi/rss.xml | International | 200 | valid, 37 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://feeds.bbci.co.uk/mundo/rss.xml | International | 200 | valid, 34 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://feeds.bbci.co.uk/russian/rss.xml | International | 200 | valid, 33 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://feeds.bbci.co.uk/turkce/rss.xml | International | 200 | valid, 16 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://feeds.bbci.co.uk/ukrainian/rss.xml | International | 200 | valid, 17 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://feeds.bbci.co.uk/news/world/rss.xml | International | 200 | valid, 37 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.counterextremism.com/rss.xml | International | 200 | valid, 10 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://rss.dw.com/xml/rss-ar-all | International | 200 | valid, 44 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://rss.dw.com/xml/rss-es-all | International | 200 | not a feed | returned HTML or an error page, not RSS/Atom (not XML: syntax error: line 1, column 0) |
| https://rss.dw.com/xml/rss-fr-all | International | 200 | not a feed | returned HTML or an error page, not RSS/Atom (not XML: syntax error: line 1, column 0) |
| https://rss.dw.com/xml/rss-hi-all | International | 200 | not a feed | returned HTML or an error page, not RSS/Atom (not XML: syntax error: line 1, column 0) |
| https://rss.dw.com/xml/rss-pt-all | International | 200 | not a feed | returned HTML or an error page, not RSS/Atom (not XML: syntax error: line 1, column 0) |
| https://rss.dw.com/xml/rss-ru-all | International | 200 | valid, 75 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.dw.com/en/top-stories/s-9097/rss | International | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://rss.dw.com/xml/rss-tr-all | International | 200 | not a feed | returned HTML or an error page, not RSS/Atom (not XML: syntax error: line 1, column 0) |
| https://www.equaltimes.org/spip.php?page=backend&lang=en | International | 200 | valid, 20 items | stale, newest item 316 days old |
| https://www.fairobserver.com/feed | International | 403 | HTTP 403 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://www.france24.com/ar/rss | International | 200 | valid, 24 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.france24.com/en/rss | International | 200 | valid, 24 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.france24.com/es/rss | International | 200 | valid, 24 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.france24.com/fr/rss | International | 200 | valid, 24 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://globalextremism.org/feed/ | International | 200 | not a feed | returned HTML or an error page, not RSS/Atom (not XML: syntax error: line 1, column 0) |
| https://gnet-research.org/feed/ | International | 200 | valid, 10 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.theguardian.com/world/rss | International | 200 | valid, 45 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.hrw.org/rss | International | 401 | HTTP 401 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://www.hrw.org/rss/region/europe-central-asia | International | 401 | HTTP 401 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://www.hrw.org/rss/news | International | 401 | HTTP 401 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://www.isdglobal.org/feed/ | International | 200 | valid, 0 items | feed has no items |
| https://www.isdglobal.org/feed/ | International | 200 | valid, 0 items | feed has no items |
| https://www.interpol.int/rss | International | 503 | HTTP 503 | server busy or rate limited when tested |
| https://www.minorityrights.org/feed/ | International | 403 | HTTP 403 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://www.ohchr.org/en/rss.xml | International | 200 | valid, 10 items | stale, newest item 77 days old |
| https://www.ohchr.org/en/news/rss.xml | International | 403 | HTTP 403 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://www.rfi.fr/ar/rss | International | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://www.rfi.fr/en/rss | International | 200 | valid, 19 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.rfi.fr/es/rss | International | 200 | valid, 29 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.rfi.fr/fr/rss | International | 200 | valid, 23 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.rfi.fr/pt/rss | International | 200 | valid, 22 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.ansa.it/sito/ansait_rss.xml | Italy | 200 | valid, 28 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.theguardian.com/world/italy/rss | Italy | 200 | valid, 20 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.rainews.it/rss/tutti | Italy | 200 | valid, 40 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.repubblica.it/rss/homepage/rss2.0.xml | Italy | 200 | valid, 30 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.japantimes.co.jp/feed/ | Japan | 200 | valid, 30 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www3.nhk.or.jp/rss/news/cat0.xml | Japan | 200 | valid, 7 items | stale, newest item 74 days old |
| https://www.koreatimes.co.kr/www/rss/world.xml | South Korea | 200 | valid, 24 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://feeds.bbci.co.uk/news/world/latin_america/rss.xml | Latin America | 200 | valid, 17 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.theguardian.com/world/americas/rss | Latin America | 200 | valid, 20 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://feeds.bbci.co.uk/news/world/middle_east/rss.xml | Middle East | 200 | valid, 36 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.theguardian.com/world/middleeast/rss | Middle East | 200 | valid, 20 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.eluniversal.com.mx/rss.xml | Mexico | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://www.jornada.com.mx/rss/edicion.xml | Mexico | 200 | valid, 102 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml | North America | 200 | valid, 21 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.premiumtimesng.com/feed | Nigeria | 200 | valid, 15 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://punchng.com/feed/ | Nigeria | 200 | valid, 30 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.discriminatie.nl/rss | Netherlands | 403 | HTTP 403 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://feeds.nos.nl/nosnieuwsalgemeen | Netherlands | 200 | valid, 20 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.nrc.nl/rss/ | Netherlands | 200 | valid, 161 items | feed text restricts to personal / non-commercial use |
| https://www.volkskrant.nl/voorpagina/rss.xml | Netherlands | 200 | valid, 78 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.vg.no/rss/feed/?format=rss | Norway | 200 | valid, 10 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.rnz.co.nz/rss/national.xml | New Zealand | 200 | valid, 47 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.publico.pt/rss | Portugal | 403 | HTTP 403 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://www.rtp.pt/noticias/rss | Portugal | 200 | valid, 50 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://english.alarabiya.net/tools/rss | Saudi Arabia | 403 | HTTP 403 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://www.arabnews.com/rss.xml | Saudi Arabia | 403 | HTTP 403 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://www.straitstimes.com/news/world/rss.xml | Singapore | 200 | valid, 50 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.bangkokpost.com/rss/data/topstories.xml | Thailand | 402 | HTTP 402 | not usable |
| https://www.dailysabah.com/rssFeed/turkey | Turkey | 200 | valid, 44 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.hurriyetdailynews.com/rss | Turkey | 200 | valid, 0 items | feed has no items |
| https://www.trtworld.com/rss | Turkey | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://cst.org.uk/rss | United Kingdom | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://cst.org.uk/news/rss | United Kingdom | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://www.theguardian.com/world/antisemitism/rss | United Kingdom | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://www.theguardian.com/uk/ukcrime/rss | United Kingdom | 200 | valid, 20 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.theguardian.com/politics/far-right/rss | United Kingdom | 200 | valid, 20 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.theguardian.com/world/hate-crime/rss | United Kingdom | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://www.theguardian.com/world/islamophobia/rss | United Kingdom | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://www.theguardian.com/world/neo-nazism/rss | United Kingdom | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://www.theguardian.com/society/race/rss | United Kingdom | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://www.theguardian.com/world/racism/rss | United Kingdom | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://www.hopenothate.org.uk/feed | United Kingdom | 403 | HTTP 403 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://hopenothate.org.uk/feed/ | United Kingdom | 403 | HTTP 403 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://www.runnymedetrust.org/rss | United Kingdom | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://www.aclu.org/rss.xml | United States | 200 | valid, 10 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.adl.org/rss/news | United States | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://www.cair.com/press_releases/feed/ | United States | 403 | HTTP 403 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://www.cfr.org/rss | United States | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://www.naacp.org/feed | United States | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://www.npr.org/rss/rss.php?id=1001 | United States | - | no response (ReadTimeout) | could not connect from this machine |
| https://feeds.npr.org/1001/rss.xml | United States | 200 | valid, 10 items | feed text restricts to personal / non-commercial use |
| https://rss.nytimes.com/services/xml/rss/nyt/World.xml | United States | 200 | valid, 51 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.propublica.org/feeds/propublica/main | United States | 200 | valid, 20 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.splcenter.org/rss.xml | United States | 403 | HTTP 403 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://www.splcenter.org/feed/ | United States | 403 | HTTP 403 | refused our request (bot protection or login); we do not disguise the User-Agent |
| https://www.splcenter.org/hatewatch/rss.xml | United States | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://www.start.umd.edu/rss.xml | United States | 200 | valid, 10 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.thetrace.org/feed/ | United States | 200 | valid, 10 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.vice.com/en/rss | United States | 200 | valid, 10 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.vox.com/rss/index.xml | United States | 200 | valid, 10 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.hatecrimereport.com/feed | United States | - | no response (ConnectError) | could not connect from this machine |
| https://www.standwithus.com/rss | United States | 200 | valid, 10 items | valid, left out to keep the list at about 40 (duplicate coverage of a feed already in the list) |
| https://www.hatefulfreedom.org/feed | United States | - | no response (ConnectError) | could not connect from this machine |
| https://mg.co.za/feed/ | South Africa | 404 | HTTP 404 | URL does not exist (guessed address) |
| https://www.news24.com/news24/rss | South Africa | 404 | HTTP 404 | URL does not exist (guessed address) |

## Disabled on 2026-10-21 (owner decision)

The Guardian (3 feeds), ABC News Australia and the BBC (BBC News UK, BBC Mundo) are switched off in `backend/feeds.json` (`"enabled": false`, with a `disabled_reason`). Their own feed text says "All rights reserved" or points to terms that restrict reuse. They stay in the file so they can be switched on again after a lawyer has looked at the publishers' terms and at German press-snippet law (section 87f UrhG). Le Monde, NRC and NPR were never added for the same reason.
