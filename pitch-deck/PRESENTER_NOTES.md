# Nazar Pitch Deck — Presenter Notes

> **Audience:** Investors, strategic partners, design-partner customers
> **Length:** 15–18 minutes for the deck, plus 5 minutes of live product demo, plus Q&A
> **Tone:** Operator-led. Specific. No hand-waving. Numbers over adjectives.

---

## 1. Running the deck

### Open it
```bash
cd pitch-deck
python3 -m http.server 7000
# Open http://localhost:7000 in Chrome
```

### Reveal.js shortcuts
| Key | Action |
|---|---|
| `→` / `Space` | Next slide |
| `←` | Previous slide |
| `F` | Fullscreen |
| `S` | Speaker view (separate window with notes and timer) |
| `Esc` | Slide overview |
| `B` | Black out screen — useful when you want eyes on you, not the deck |
| `?` | Help overlay |

### Export to PDF
1. Open in **Chrome** with `?print-pdf` appended to the URL.
2. `Cmd/Ctrl + P` → **Save as PDF** → Layout: **Landscape**, Margins: **None**, Background graphics: **On**.

---

## 2. Slide-by-slide talk track

The deck has 16 slides organised in five movements: **hook (1–2)**, **problem and timing (3–4)**, **solution and moat (5–9)**, **competition, market, business model (10–12)**, **traction, roadmap, team, ask (13–16)**.

### Slide 01 — Title

> *Pause for two seconds before saying anything. Let the headline land.*
>
> "Nazar is the WhatsApp CRM that remembers every customer. Built for the 63 million Indian SMBs whose entire business runs on WhatsApp — and who lose deals every week because the tools they use forget what was said yesterday."

### Slide 02 — The Hook

Read the three card headers in order: **500M+ users, every existing tool forgets, the first CRM with memory.**

> "Three sentences. WhatsApp is the channel. Every existing tool is a stateless inbox. Nazar is the first one with persistent memory."
>
> Then stop. The most powerful question after this slide is silence — let the listener ask "how does memory work?". That's your cue for slide 5 and 6.

### Slide 03 — The Problem

You have four hard data points. Use them — don't paraphrase. Pick the one your audience will react to most:
- For **investors**: lead with 68% of leads getting a delayed reply (acquisition cost wasted).
- For **operators**: lead with the ₹60K/month spent on copy-paste staff (immediate ROI).
- For **technical buyers**: lead with "zero existing tools remember the customer" (the architectural gap).

> "These are real numbers from real interviews. We talked to 42 SMB owners. The same five complaints, every conversation."

### Slide 04 — Why Now

The most important slide for an investor. Three structural waves, all happening *together*:

1. **Distribution unlocked** — Meta opened the API, costs dropped 80%.
2. **Cost viable** — LLM inference now cheaper than SMS.
3. **Regulation favourable** — Meta is removing competitors in Jan 2026.

> "Each wave alone wouldn't be enough. All three at once is a once-in-a-decade window. Razorpay had the same window in 2014. Khatabook had it in 2018. We have it right now."

### Slide 05 — The Solution

Walk the six cards quickly. Don't get stuck on any one.

> "Memory is the engine. Inbox is the cockpit. Pipeline is the output. Campaigns are the lever. Knowledge base is the source of truth. Smart handoff is the safety net. Six modules, one product, connected in five minutes."
>
> Punchline: "Most CRMs make the owner do the data entry. Nazar **is** the data entry — it just happens automatically while customers chat."

### Slide 06 — The Moat (Memory is the product)

This is the slide that wins or loses an investor. Slow down.

> "Every WhatsApp tool today treats messages as a stateless pipe. Nazar treats every contact as a relationship database. That single architectural choice changes everything downstream — from reply quality, to pipeline accuracy, to the switching cost we build over 90 days."
>
> Read the right column out loud: "AI retrieves history before composing… past objections inform the response… anyone on the team picks up where the AI left off." Each of those sentences is a feature only Nazar has.

### Slide 07 — Live Demo (in-deck)

This is the money slide. Spend two to three minutes here.

1. Read the chat exchange aloud, doing both voices.
2. Then narrate the right column: "In four messages, six things happened — replied in two seconds, qualified the lead, booked a meeting, stored a fact for the future, updated the pipeline, pinged the owner."
3. Land the closing line: **"The owner did nothing. The deal moved anyway."**

After this, transition to the live product demo (see Section 3 below).

### Slide 08 — Product Dashboard

> "This is what the owner sees on their phone every morning. Sixteen point three lakh in active pipeline. Eighty-five percent of replies handled by AI. Two-second response time. Eleven times more leads handled per hour of owner time. No spreadsheets. No data entry."

### Slide 09 — Compliance Moat (Meta Jan 2026)

A second-order moat, often underappreciated.

> "From January 2026, Meta is restricting general-purpose AI chatbots on WhatsApp. Most current vendors built their AI as a ChatGPT wrapper — they will spend Q1 2026 rebuilding their core product to stay on the platform. Nazar's architecture was designed compliant from day one. We will spend Q1 2026 acquiring their customers."

### Slide 10 — Competition

Walk the table left to right. Hit two punchlines:

> "WATI, Interakt, AiSensy, and Gallabox are broadcast tools or ticket-style inboxes. They send messages. Nazar **is** the salesperson."
>
> "Western CRMs like Intercom, HubSpot, and Zoho CRM Plus are built for $74-per-month customers. We're built for ₹1,999. They literally can't price-compete in this segment."

### Slide 11 — Market

> "Forty thousand crore TAM. We don't need to win the market. We need 0.5 percent of it to be a 360 crore business in three years."
>
> Reference Khatabook — comparable scale-up story with a less sticky product. "WhatsApp memory is stickier than a ledger."

### Slide 12 — Business Model

Three plans. Growth is the wedge at ₹5,999/month. Why the LTV/CAC works:

> "Nazar saves a typical SMB more than ₹50,000 a month in staff time. Justifying ₹6,000 is a one-conversation sale. Word-of-mouth in SMB networks is real — every Razorpay merchant talks to ten others."

### Slide 13 — Traction

Be specific. The credibility comes from concrete numbers:

> "This isn't a deck product. It's a shipped product. Forty-two thousand lines of production code. Seven hundred and eighty backend tests passing. A hundred-plus REST endpoints. Working WhatsApp integration, working AI failover, working Razorpay billing, working multi-tenant auth. Pilot customers onboarding in Q1."
>
> "If you sign today, you can use it tomorrow."

### Slide 14 — Roadmap

> "Q1 is now — pilots and production hardening. Q2 we launch publicly with founder-led sales. Q3 we go self-serve and sign integration partners. Q4 we expand internationally. Eighteen months from now: five thousand paying customers, three crore ARR, Series A ready."

### Slide 15 — Team

Be honest about the solo-founder stage. Frame it as a strength:

> "I built v1.0 alone in three months. Production-grade, deployed, with billing. Now imagine what five of us can do."
>
> Capital enables the first four hires: a co-founder with SMB GTM experience, a senior growth lead, and two engineers.

### Slide 16 — The Ask

Three things, in this order: **capital, network, wisdom.** Don't lead with money.

> "Capital lets us hire four people, run paid acquisition, and hit three crore ARR in 18 months. Your network lets us reach the SMB portfolio and the Razorpay, Zoho, and Tally ecosystems. Your operator wisdom lets us avoid the mistakes you've already paid for."
>
> Close: "The window is open right now. WhatsApp, AI, and Indian SMBs — this is the moment. We'd like you to be part of it."
>
> Then stop talking. Wait.

---

## 3. Live product demo (after Slide 07 or 13)

When the audience asks to see the product:

```bash
cd /home/workspace/Nazar/nazar
./demo.sh
```

The dashboard will be at `http://localhost:8001`.

### Five-minute demo flow

1. **Inbox** — "Every WhatsApp conversation in one place. The AI has already replied to most of them."
2. **Open any conversation** — Show the AI reply quality, the per-customer memory panel on the right, the pipeline stage and lead score.
3. **Test mode** — Type a question as the customer. Show the AI reply in real time. *This is the aha moment.*
4. **Knowledge base** — Add a fact like "We are running a 10% Diwali discount this week." Save.
5. **Back to the conversation** — Ask about the discount. Show that the AI has it instantly. No retraining.
6. **Pipeline view** — Show all six stages, the deal values, the auto-classification.
7. **Handoff** — Open a conversation where the AI has paused and escalated. Show the reason and the inline owner reply.

### Built-in interactive tour

The dashboard ships with a self-guided tour. From any logged-in screen, click the "Take a 3-minute tour" chip in the bottom-right. The product walks the customer through every value moment. Use this if you have to send the demo URL to someone who isn't on the call.

---

## 4. Common Q&A — prepared answers

**"How is this different from a chatbot?"**
> Chatbots answer FAQs. Nazar runs your sales pipeline. Memory plus auto-classification plus smart handoff is what makes it a salesperson, not a bot. Chatbots forget. Salespeople remember.

**"What if a customer doesn't want AI handling them?"**
> Smart handoff. The AI replies to routine conversations and transparently hands off complaints, negotiations, and complex cases to a human in the same inbox, with full context. The customer often doesn't notice the switch.

**"Compliance — WhatsApp policy, data residency, GST?"**
> Built on the official Cloud API. Template approval workflow. Per-contact AES encryption at rest. Razorpay-native billing with GST invoices. Fully aligned with Meta's January 2026 chatbot policy. We are more compliant than most incumbents.

**"What's your AI accuracy?"**
> Eighty-five percent of conversations are handled fully by the AI. The remaining 15 percent are auto-routed to the owner with the reason flagged. Compare that to a human team — most SMBs respond to less than 40 percent of WhatsApp leads in time.

**"What's your unfair advantage?"**
> I built v1.0 alone in three months because I lived this pain. I know exactly what to ship next. Capital lets me ship faster — it doesn't help me figure out what to ship.

**"Why won't WATI just copy this?"**
> WATI raised $23M and is built on a Shopify-style template workflow architecture. Their entire codebase assumes stateless, rules-based automation. Retrofitting persistent vector memory is a rebuild, not a feature. By the time they ship, we have 5,000 customers and a data flywheel.

**"What about Meta launching this natively?"**
> Possible. But Meta's interest is in ads and platform fees, not in being a CRM vendor. Even if they ship something, our positioning as the *Indian-language, India-priced, India-billed* layer with deeper sales tooling protects us.

**"What's the real risk to the business?"**
> Two things: (1) LLM pricing volatility — a sudden Anthropic or OpenAI price increase could compress margins; we mitigate with three-provider failover and aggressive caching. (2) Customer acquisition cost in a noisy market — the founder-led pilot phase is specifically designed to validate CAC before scaling spend.

---

## 5. Pre-presentation checklist

- [ ] Slide 01: Test the title rendering on the actual screen you'll be presenting on.
- [ ] Slide 13: Verify the production code/test/endpoint counts are still current at presentation time.
- [ ] Slide 16: Replace the placeholder phone number with your real number, or remove that line.
- [ ] Live demo: Run `./demo.sh` end-to-end on the same network you'll present on. Have a screenshot fallback ready in case of network failure.
- [ ] Backup: Export the deck to PDF (`?print-pdf` route + Chrome print) and save it locally as a fallback if Reveal.js fails.

---

## 6. After the meeting

Send a single follow-up email within four hours containing:

1. PDF of the deck.
2. The live demo URL with read-only credentials.
3. A two-line recap of the specific concern they raised, and how Nazar addresses it.
4. One concrete next step with a date.

Keep it short. The deck did the talking.
