# The positive cases, told as stories

[`cases-angreifer.yaml`](cases-angreifer.yaml) is the ground truth of the Angreifer eval, and it reads like what it
is: anchors, verbatim Normtext, `expected_category` labels. This file is the same positives told
the way a reporter would tell them — what happened, who made money, how much, and which single
sentence in the draft made it possible.

Why bother: the Angreifer pass is supposed to see the story *before* it happens, from the draft
alone. If you can't tell the story, you can't judge whether the pass found it. Each entry ends
with a link to press coverage of the aftermath, as a starting point for your own research.

Two caveats on the links. They are **secondary sources about the consequences**, not the ground
truth — the ground truth is the quoted passage in the Drucksache PDF, checked against the primary
text on 2026-09-05. And they are reporting on what happened *afterwards*, which the model never
sees: the pass gets the draft as it stood before the vote, nothing else.

Cases on the frozen `test` split are marked *(test)*; read them only to judge a test run.

| Case | Drucksache | In one line |
|---|---|---|
| R-B1 *(test)* | 14/23 (1998) | A repair replaced "all shares" with "95 percent" — and invented the share deal |
| R-A1 | 19/13437 (2019) | Twenty-two years later the same legislature repaired it with another number |
| R-A2 *(test)* | 19/4455 (2018) | A certificate says the trader is registered. Not that he paid |
| R-A3 *(test)* | 19/4455 (2018) | The marketplace is liable only *after* the tax office writes a letter |
| R-B2 | 17/15 (2009) | 7 percent on the room, 19 on breakfast — and the hotel decides which is which |
| R-B3 *(test)* | 17/8877 (2012) | *Inverse control:* the draft that switched from dated cuts to a monthly one |
| R-C1 | 18/10207 (2016) | *Inverse control:* the law that closed the sausage loophole |
| R-D1 | 18/8045 (2016) | *Positive control:* the draft that red-teamed itself |
| R-E1 | 16/2712 (2006) | Cum-ex: the seller picks who withholds, the buyer's bank certifies anyway |

---

## The threshold that built an industry — twice

### R-B1 · Steuerentlastungsgesetz 1999/2000/2002 (BT-Drs. 14/23)

Before 1999, a company that wanted to buy German property without paying real estate transfer
tax had an easy time of it: the law taxed the transfer of **all** shares in a property-owning
company, so you bought 99 percent and left the rest with someone else. The 1999 draft fixed
that. It replaced the word "alle" with "mindestens 95 vom Hundert der".

That one substitution is the whole story. It closed a loophole you could drive a truck through
and opened a narrower one you could drive a very profitable truck through — and, crucially, it
told everyone exactly how wide the new one was. Buy 94.9 percent, park 5.1 percent with a
co-investor, hold five years, pay nothing. Advisory firms turned it into a product. By the time
journalists put a number on it, the arrangement was costing the states around **one billion euros
a year**, while every private buyer of a flat paid the tax in full.

**What the pass has to see in the draft:** that a threshold below 100 percent is a set of
building instructions. Nothing else in the document is wrong — the references are clean, the
consequential amendments are complete.

Coverage: [CORRECTIV, "Eine Milliarde verschenkt" (21.06.2018)](https://correctiv.org/aktuelles/wem-gehoert-hamburg/2018/06/21/eine-milliarde-verschenkt/)

### R-A1 · Grunderwerbsteuer-Reform (BT-Drs. 19/13437) ⭐

The sequel, and the reason this whole eval exists. In 2019 the government moved against share
deals. Its instrument: lower the threshold from 95 to 90 percent and stretch the holding period
from five years to ten.

Experts said in the Finanzausschuss hearing in October 2019 what anyone who had watched 1999
could have said — a lower number is still a number. The bill then sat untouched for eighteen
months, during which share deals carried on exactly as before, and passed in April 2021 with the
threshold logic intact. The new arrangement is 89.9 percent to the buyer, 10.1 percent to an
anchor investor, ten years instead of five. More expensive. Not prevented. The Bundestag's own
write-up of the vote was headlined with the doubt that it would contain anything.

**What the pass has to see in the draft:** the same defect as B1, in a document that also
contains the word "Missbrauch" repeatedly. B1 and A1 are twenty-two years apart and are the
eval's internal control: a pass that fires on the 2021 draft but not the 1998 one is keying on
the vocabulary of the Begründung, not on the norm.

Coverage: [CORRECTIV, "Neues Gesetz: Immobilienkonzerne sollen künftig beim Kauf Steuern zahlen" (14.04.2021)](https://correctiv.org/aktuelles/wem-gehoert-die-stadt/2021/04/14/neues-gesetz-immobilienkonzerne-sollen-kuenftig-beim-kauf-steuern-zahlen/) ·
also [taz, "Steuertrick soll möglich bleiben" (12.03.2021)](https://taz.de/Union-zur-Reform-der-Grunderwerbsteuer/!5754639/)

---

## The certificate that proves the wrong thing

Both cases come from the same draft, the Jahressteuergesetz 2018 (BT-Drs. 19/4455). The problem
it was written for was real and large: traders from outside the EU sold through German
marketplaces, collected VAT from German customers and never passed it on. Honest sellers were
undercut by 19 percent, and the estimates of what the state was losing ran into the hundreds of
millions a year.

### R-A2 · The liability shield

The mechanism the draft chose: marketplaces become liable for their sellers' unpaid VAT — unless
the seller hands over a certificate. And the certificate confirms that the trader is
**registered** with a German tax office. Not that he has paid anything.

So the marketplace collects a piece of paper, the paper switches off the liability, and the
marketplace's reason to care about whether the tax ever arrives switches off with it. Obligation
and advantage run on separate tracks. The certificate solution didn't last: the Commission opened
infringement proceedings, and by 2021/22 it had been replaced by the VAT ID.

**The sentence that does it:** „Der Betreiber haftet nicht nach Absatz 1, wenn er eine
Bescheinigung nach § 22f Absatz 1 Satz 2 … vorlegt."

### R-A3 · The clock that starts too late

The same draft, one paragraph on. Liability for a delinquent seller begins only **after** the tax
office has noticed him, opened proceedings, and notified the marketplace — and it covers only
business done after that letter arrives.

Everything before the letter is free. And a trader who receives one registers again under a new
company name, at which point the clock starts over from zero. The penalty is structurally unable
to reach money already earned.

**The sentence that does it:** „… soweit das dem Umsatz zugrunde liegende Rechtsgeschäft nach dem
Zugang der Mitteilung abgeschlossen worden ist."

Coverage for both: [Handelsblatt, "Chinesische Händler schaden Fiskus und Verbrauchern" (09.08.2018)](https://www.handelsblatt.com/unternehmen/handel-konsumgueter/online-handel-gefaehrlicher-east-commerce-haendler-aus-china-schaden-fiskus-und-verbrauchern/22896762.html)

---

## R-B2 · Seven percent on the room, nineteen on the breakfast

### Wachstumsbeschleunigungsgesetz (BT-Drs. 17/15)

The hotel VAT cut of 2009 is the one German tax measure with its own nickname — the
"Mövenpick-Steuer", after the hotel group whose owner had donated to the FDP. The politics are
famous. The drafting defect is not.

The new provision is a single sentence: the reduced 7 percent rate applies to "die Vermietung von
Wohn- und Schlafräumen, die ein Unternehmer zur kurzfristigen Beherbergung von Fremden
bereithält." Room: 7 percent. Breakfast, parking, spa, wifi: 19 percent. And the law says nothing
whatsoever about how to split a package price between the two.

Whoever writes the price list decides. A hotel selling one bundled price gets to draw the line
between the 7-percent part and the 19-percent part itself, and every euro moved across that line
is worth twelve percentage points. The dispute went on for more than a decade — a BMF letter in
March 2010, years of argument over what a breakfast is worth, a BFH ruling in 2013, an ECJ
judgment in 2018 that had people asking whether the split survived at all. The gap stayed open
because the statute never closed it.

**What the pass has to see:** a rate that splits inside a service the provider defines, with no
allocation standard. This is also the one case where the ordinary Lektor prompt has a fair shot
at it (as `unklarheit`) — a useful bridge between the two passes.

Coverage: [Handelsblatt, "EuGH-Urteil: Die Mövenpick-Steuer wackelt" (22.05.2018)](https://www.handelsblatt.com/politik/deutschland/eugh-urteil-die-moevenpick-steuer-wackelt/22581284.html)

---

## R-B3 · The deadline as a starting gun — the second inverse control

### PV-Novelle EEG (BT-Drs. 17/8877)

Solar tariffs were too generous, so the government cut them — on a date, announced in advance.
Which is a promise that anything switched on before the date keeps the old rate for twenty years.

The market did the obvious thing. Germany added about 7.5 gigawatts of photovoltaics in 2011, and
roughly **3 gigawatts of that — around 40 percent of the whole year — went online in December
alone**, ahead of the 15 percent cut on 1 January 2012. Then the 2012 novella set the next cut for
1 April. Every rush produced exactly the costs the cut was meant to avoid.

The draft in this eval is the answer to December 2011: it switches to a monthly cut "um künftig
Vorzieheffekte wie im Dezember 2011 zu verhindern", and brings the law into force early so that no
new rush can build up. The Begründung records the December numbers itself.

**Which makes it an inverse test, like R-C1.** The dated-cut attack is closed in the text in front
of the pass; reporting it as open is the false positive. A narrow window in a transitional rule —
say, for ground-mounted plants switched on by 30 June 2012 — would be a separate finding.

Coverage: [pv magazine, "Bundesnetzagentur bestätigt Photovoltaik-Rekordzubau" (09.01.2012)](https://www.pv-magazine.de/2012/01/09/bundesnetzagentur-besttigt-photovoltaik-rekordzubau/)

---

## R-C1 · The sausage loophole — the inverse control

### 9. GWB-Novelle (BT-Drs. 18/10207)

German cartel fines were imposed on legal persons, not on businesses. So when the
Bundeskartellamt fined members of a sausage cartel, some of them dissolved or merged away the
company that had been fined. The company was gone; the business carried on; the fine collapsed.
Over several proceedings the office had to write off fines in the hundreds of millions — LTO puts
the total dropped across those proceedings at around 238 million euros; a further 110 million
went the same way in the batch the Bundeskartellamt reported in June 2017.

The draft in this eval is the **repair**: it extends liability to legal successors and to whoever
continues the business in "wirtschaftlicher Kontinuität".

**Which makes it the inverse test.** Run the pass against 18/10207 and the loophole is *closed* in
the text in front of it. Reporting it again as open is the false positive. Red-teaming the repair
itself is the behaviour we want.

Coverage: [LTO, "Wurstlücke bringt Staat um weitere 110 Millionen Euro" (26.06.2017)](https://www.lto.de/recht/kanzleien-unternehmen/k/kartellverfahren-wurstkartell-wurstluecke-bussgelder-umstrukturierungen-bundeskartellamt)

---

## R-D1 · The draft that red-teamed itself

### Investmentsteuerreformgesetz (BT-Drs. 18/8045)

Cum-cum: hold German shares across the dividend date through someone who can reclaim the
withholding tax, split the proceeds. Estimates of what it cost Germany run to **28.5 billion
euros**. The 2016 reform answered with § 36a EStG — a 45-day minimum holding period, a
requirement to carry at least 30 percent of the price risk, and a €20,000 threshold below which
none of it applies.

What makes this the control case is the Begründung. It does the attacker's arithmetic out loud:
the threshold exists because "sich der administrative und finanzielle Aufwand für eine
Steuerumgehungsgestaltung nur bei entsprechend großer Steuerersparnis rechnet", and the 30 percent
risk test exists so that nobody transfers bare ownership while keeping the economic risk "durch
andere Rechtsgeschäfte (z. B. Optionen oder Future-Kontrakte)". That is precisely the reasoning
this pass is meant to automate — here a legislature did it unaided.

**Expected behaviour: almost nothing.** At most the leftover — the €20,000 exemption applies per
taxpayer and tax year, so spreading the position over several acquiring companies keeps each one
below it. That only pays with many vehicles; several custody accounts of the same taxpayer do not
help. If the pass reports five
more attacks on this document, it is too loud, and this is the most sensitive precision indicator
in the file: the text is full of abuse vocabulary and a badly calibrated attacker lights up on it.

Coverage: [CORRECTIV, "CumEx-Files 2.0" (21.10.2021)](https://correctiv.org/top-stories/2021/10/21/cumex-files-2/)

---

## R-E1 · Cum-ex

### Jahressteuergesetz 2007 (BT-Drs. 16/2712)

Short sales across the dividend date had long produced two tax certificates for one withholding.
The 2007 draft meant to close that: § 44 Abs. 1 Satz 3 EStG-E makes "das den Verkaufsauftrag
ausführende inländische Kreditinstitut oder Finanzdienstleistungsinstitut" withhold the tax. The
buyer's custodian keeps issuing the certificate "wie bisher" (§ 45a Abs. 3 EStG-E) — without any
link to whether the tax was actually paid.

The attack is one choice: the seller routes the sale through a foreign bank. No domestic
institution executes the order, so nobody withholds, and the buyer's bank still certifies a tax
the buyer then reclaims. The Einzelbegründung to § 20 says the aim is to collect as much tax at
source as is later credited — the draft states the goal and misses it in the same stroke. The
damage is put in the tens of billions of euros; the gap closed only on 1 January 2012 with the
OGAW-IV-Umsetzungsgesetz, and in 2021 the BGH held that cum-ex was always tax evasion.

**Expected behaviour:** `adressatenwahl` on the withholding duty, with `entkopplung` and
`nachweisluecke` as secondary patterns. The case is only partly blind: the prompt was drafted with
this case in mind.

---

## Pattern coverage

The attack patterns (`Muster` in `backend/analysis/schema.py`) the positives exercise. The primary
pattern is the record's `expected_category`; secondary ones are named in its `story`. Inverse and
negative controls count for precision, not here.

| Muster | Positives | |
|---|---|---|
| `schwellenwert` | R-A1, R-B1, R-D1 | well covered, twice by the same legislature 22 years apart |
| `entkopplung` | R-A2, R-B2 (secondary), R-E1 (secondary) | covered |
| `adressatenwahl` | R-E1 | one case; R-C1 carries it as an inverse control |
| `nachweisluecke` | R-A2 (secondary), R-E1 (secondary) | never primary |
| `sanktionsarithmetik` | R-A3 | one case |
| `definitionsmacht` | R-B2 | one case |
| `zeitfenster` | R-A3 (secondary) | never primary; R-B3 is its inverse control |
| `kumulation` | — | **no case** |
| `anwendungsbereich` | — | **no case** |
| `vollzugsspielraum` | — | **no case** |

Recall on the three uncovered patterns is **unmeasurable, not zero** — say so with every
evaluation. `vollzugsspielraum` is the most painful gap: it is the only pattern whose attacker is
the state, and the one that matters for civil liberties.

Candidates for the next research round, all under the same selection rule (the exploitable
provision was introduced or materially changed by an identifiable Gesetzentwurf whose PDF is on
dserver.bundestag.de):

- `kumulation` — double funding from federal and Land programmes without any cross-check.
- `anwendungsbereich` — relocating the registered office to escape a new reporting duty.
- `vollzugsspielraum` — an intrusive power from the 21st Wahlperiode whose purpose limitation
  falls short of the power itself.

---

## Where the rest lives

- [`cases-angreifer.yaml`](cases-angreifer.yaml) — the ground truth: anchors, expected attack
  patterns, `requires_context`, splits, the forbidden claims of the inverse controls and of the
  negative controls (R-F1–R-F7) that measure precision
- [`../README.md`](../README.md) — how to run the eval
