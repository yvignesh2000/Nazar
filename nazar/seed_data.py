"""
Seed script — populates Nazar with realistic demo data.
Uses the actual encrypted data layer so everything works properly.
"""
import sys
import os
from pathlib import Path

# Add core to path
sys.path.insert(0, str(Path(__file__).parent / "core"))

from contact_manager import (
    create_contact, update_contact, move_stage, update_lead_score,
    add_tag, save_message, list_contacts, get_contact_by_phone,
    normalize_phone, PIPELINE_STAGES,
)
from handoff_manager import trigger_handoff

from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))


def ts(days_ago=0, hours_ago=0, minutes_ago=0):
    """Generate ISO timestamp relative to now."""
    return (datetime.now(IST) - timedelta(days=days_ago, hours=hours_ago, minutes=minutes_ago)).isoformat()


# -----------------------------------------------------------------------
#  CONTACTS TO SEED
# -----------------------------------------------------------------------
CONTACTS = [
    {
        "name": "Priya Sharma",
        "phone": "+919876543210",
        "company": "TechBridge Solutions",
        "source": "WhatsApp",
        "stage": "Proposal",
        "deal_value": 24000,
        "lead_score": 78,
        "tags": ["enterprise", "hot-lead"],
        "assigned_to": "owner",
        "notes": "Interested in Growth Plan for her team of 12. Asked about API integration.",
        "last_contacted_days_ago": 1,
        "conversations": [
            {"days_ago": 3, "messages": [
                ("inbound", "Hi, I saw your ad about WhatsApp automation. Can you tell me more?", "contact"),
                ("outbound", "Hi Priya! Thanks for reaching out. Nazar helps businesses automate WhatsApp conversations with AI. What kind of business are you running?", "bot"),
                ("inbound", "I run a software consulting firm — TechBridge Solutions. We get about 50 enquiries a day on WhatsApp and can't keep up.", "contact"),
                ("outbound", "That's exactly what Nazar is built for! With 50 daily enquiries, our Growth Plan would be perfect. The AI handles initial qualification and FAQs, then hands off to your team for complex deals. Would you like to see a demo?", "bot"),
                ("inbound", "Yes please! Can we do it tomorrow?", "contact"),
            ]},
            {"days_ago": 2, "messages": [
                ("outbound", "Hi Priya! Ready for the demo? I'll walk you through the pipeline view, AI memory, and broadcast features.", "bot"),
                ("inbound", "Yes, let's go! Also, do you support API integration? We use Zoho CRM.", "contact"),
                ("outbound", "Great question! Our Enterprise Plan includes full API access and we have a Zoho CRM integration in beta. Let me show you the pipeline first...", "bot"),
                ("inbound", "This looks amazing. The AI memory feature is exactly what we need. What's the pricing for Growth Plan?", "contact"),
                ("outbound", "Growth Plan is ₹7,999/month — includes up to 5,000 contacts, AI memory, broadcasts, and team collaboration for 3 users. For your team of 12, Enterprise at ₹14,999/month might be better. Want me to prepare a proposal?", "bot"),
            ]},
            {"days_ago": 1, "messages": [
                ("inbound", "Yes, send me the proposal for Enterprise Plan. Also check if you can do annual billing discount.", "contact"),
                ("outbound", "I'll prepare the Enterprise proposal with annual billing options. We offer 20% off on annual plans, so it would be ₹11,999/month billed annually. I'll send the detailed proposal by tomorrow.", "human"),
            ]},
        ],
    },
    {
        "name": "Rahul Mehta",
        "phone": "+919823456789",
        "company": "FreshBasket Groceries",
        "source": "Instagram",
        "stage": "Negotiation",
        "deal_value": 36000,
        "lead_score": 85,
        "tags": ["d2c", "high-value", "annual"],
        "assigned_to": "owner",
        "notes": "Wants to use Nazar for order updates + customer support. Negotiating Enterprise annual deal.",
        "last_contacted_days_ago": 0,
        "conversations": [
            {"days_ago": 5, "messages": [
                ("inbound", "Hi! I run FreshBasket — an online grocery delivery service. We need WhatsApp automation for order updates and customer queries.", "contact"),
                ("outbound", "Hi Rahul! Welcome. Nazar is perfect for D2C businesses like FreshBasket. We can automate order confirmations, delivery updates, and handle customer support queries. How many orders do you process daily?", "bot"),
                ("inbound", "About 200-300 orders a day. We currently have 3 people just answering 'where is my order' questions on WhatsApp.", "contact"),
                ("outbound", "That's a huge time saver! Our AI can handle order status queries automatically, freeing up your team for complex issues. With 200-300 daily orders, you'd want the Enterprise Plan. Want me to set up a trial?", "bot"),
            ]},
            {"days_ago": 2, "messages": [
                ("inbound", "We tried the trial and it's great! But ₹14,999/month is steep for us. Can you do ₹10,000?", "contact"),
                ("outbound", "I understand budget is important, Rahul. Let me check what we can offer. For an annual commitment, we can do ₹11,999/month. That's essentially 2.5 months free.", "human"),
                ("inbound", "Annual commitment works for us. Can you also throw in the API integration for our order system?", "contact"),
                ("outbound", "API access is included in Enterprise! I'll prepare the annual contract at ₹11,999/month (₹1,43,988/year). The API docs are ready for your dev team. Shall I send the contract?", "human"),
            ]},
            {"days_ago": 0, "messages": [
                ("inbound", "Sounds good. One last thing — can you do ₹11,000 flat? If yes, we'll sign today.", "contact"),
                ("outbound", "Let me check with the team on that. I'll get back to you within the hour, Rahul.", "human"),
            ]},
        ],
    },
    {
        "name": "Anitha Krishnan",
        "phone": "+919845671234",
        "company": "Bloom Interiors",
        "source": "Google",
        "stage": "Qualified",
        "deal_value": 8000,
        "lead_score": 55,
        "tags": ["smb", "warm"],
        "assigned_to": "owner",
        "notes": "Interior design studio. Looking for appointment booking + lead capture on WhatsApp.",
        "last_contacted_days_ago": 3,
        "conversations": [
            {"days_ago": 4, "messages": [
                ("inbound", "Hello! I found you on Google. I have an interior design studio and want to automate my WhatsApp responses.", "contact"),
                ("outbound", "Hi Anitha! Welcome to Nazar. An interior design studio is a great fit — we can help with appointment scheduling, portfolio sharing, and lead qualification. How many enquiries do you get daily?", "bot"),
                ("inbound", "Maybe 10-15 per day. Mostly asking for quotes and wanting to see our portfolio.", "contact"),
                ("outbound", "Perfect! Our Starter Plan at ₹2,999/month would work great for you. The AI can share your portfolio link, answer pricing FAQs, and book consultations. Want to try it?", "bot"),
            ]},
            {"days_ago": 3, "messages": [
                ("inbound", "That sounds good but I want to think about it. Can you send me more details on email?", "contact"),
                ("outbound", "Of course, Anitha! I'll send you a detailed brochure at your email. Take your time to decide. If you have any questions, just message here anytime!", "bot"),
            ]},
        ],
    },
    {
        "name": "Arjun Patel",
        "phone": "+919912345678",
        "company": "QuickFix Auto Services",
        "source": "Referral",
        "stage": "Won",
        "deal_value": 96000,
        "lead_score": 95,
        "tags": ["enterprise", "annual", "referral-program"],
        "assigned_to": "owner",
        "notes": "Signed Enterprise annual plan. Using Nazar for service reminders + customer support. Very happy customer.",
        "last_contacted_days_ago": 2,
        "conversations": [
            {"days_ago": 10, "messages": [
                ("inbound", "Hey! Rahul from FreshBasket told me about you. I run a chain of auto service centers.", "contact"),
                ("outbound", "Hi Arjun! Great to hear from you — Rahul is one of our favorite customers! How can Nazar help QuickFix Auto?", "bot"),
                ("inbound", "We want to send service reminders, handle booking confirmations, and answer common questions like pricing and availability.", "contact"),
            ]},
            {"days_ago": 7, "messages": [
                ("outbound", "Arjun, I've set up your Nazar account with service reminder templates and FAQ responses. Your team can monitor everything from the dashboard. How's the trial going?", "human"),
                ("inbound", "It's working brilliantly! Customers love getting reminders. We've seen a 30% increase in repeat bookings already.", "contact"),
                ("outbound", "That's fantastic! Ready to go live with the full Enterprise Plan?", "human"),
                ("inbound", "Absolutely. Send me the annual contract. Also, can we be part of your referral program?", "contact"),
            ]},
            {"days_ago": 2, "messages": [
                ("outbound", "Hi Arjun! Your Enterprise annual plan is now active. Here's your referral code: QUICKFIX-REF. For every customer you refer, you get 1 month free. Welcome aboard! 🎉", "human"),
                ("inbound", "Thanks! Already told two other business owners about you guys. Great product.", "contact"),
            ]},
        ],
    },
    {
        "name": "Deepa Nair",
        "phone": "+919867543210",
        "company": "Sparkle Clean Co",
        "source": "WhatsApp",
        "stage": "New",
        "deal_value": 0,
        "lead_score": 20,
        "tags": ["new-lead"],
        "assigned_to": None,
        "notes": "",
        "last_contacted_days_ago": 0,
        "conversations": [
            {"days_ago": 0, "messages": [
                ("inbound", "Hi, I saw your post about WhatsApp bots. What is this about?", "contact"),
                ("outbound", "Hi Deepa! Thanks for reaching out. Nazar is a WhatsApp Sales Intelligence Platform that helps businesses automate customer conversations using AI. What kind of business do you run?", "bot"),
            ]},
        ],
    },
    {
        "name": "Karthik Sundaram",
        "phone": "+919934567890",
        "company": "EduFirst Academy",
        "source": "LinkedIn",
        "stage": "Qualified",
        "deal_value": 16000,
        "lead_score": 62,
        "tags": ["education", "warm"],
        "assigned_to": "owner",
        "notes": "Coaching institute chain. Wants AI for parent inquiries and fee collection reminders.",
        "last_contacted_days_ago": 2,
        "conversations": [
            {"days_ago": 6, "messages": [
                ("inbound", "Saw your LinkedIn post. We run a coaching academy with 3 branches. Parents keep messaging us on WhatsApp about fees, schedules, results. It's overwhelming.", "contact"),
                ("outbound", "Hi Karthik! Education is one of our fastest growing verticals. Nazar can handle parent FAQs, send fee reminders, share exam schedules, and even handle admission enquiries. How many parents are we talking about?", "bot"),
                ("inbound", "About 2000 parents across 3 branches. We have 5 staff members handling WhatsApp right now.", "contact"),
                ("outbound", "With 2000 parents and 5 staff, the Growth Plan at ₹7,999/month would be ideal. The AI handles routine queries (80% of messages) and your staff focuses on complex parent conversations. Want to see it in action?", "bot"),
            ]},
            {"days_ago": 2, "messages": [
                ("inbound", "The demo was good. We want to start with Growth Plan. But can we do half-yearly billing?", "contact"),
                ("outbound", "Great choice, Karthik! We offer half-yearly billing at 10% off — that's ₹7,199/month (₹43,194 for 6 months). I'll send you the setup guide and onboarding link.", "human"),
            ]},
        ],
    },
    {
        "name": "Meera Joshi",
        "phone": "+919876123456",
        "company": "StyleBox Fashion",
        "source": "Instagram",
        "stage": "Lost",
        "deal_value": 0,
        "lead_score": 15,
        "tags": ["lost-budget"],
        "assigned_to": None,
        "notes": "Budget constraints. Went with a cheaper alternative. Revisit in Q3.",
        "last_contacted_days_ago": 15,
        "conversations": [
            {"days_ago": 20, "messages": [
                ("inbound", "Hi! I run a fashion boutique and need WhatsApp automation for order tracking and new collection announcements.", "contact"),
                ("outbound", "Hi Meera! Fashion brands love Nazar — we can automate order updates, share new collection lookbooks, and handle size/availability queries. Which plan were you considering?", "bot"),
                ("inbound", "What's your cheapest plan?", "contact"),
                ("outbound", "Our Starter Plan is ₹2,999/month — includes AI auto-replies, basic pipeline, and WhatsApp API integration. Perfect for getting started!", "bot"),
            ]},
            {"days_ago": 15, "messages": [
                ("inbound", "Sorry, that's too expensive for us right now. We found something cheaper. Maybe later!", "contact"),
                ("outbound", "No problem at all, Meera! We'll be here when you're ready. Feel free to reach out anytime. Wishing StyleBox all the best! 🌟", "bot"),
            ]},
        ],
    },
    {
        "name": "Vikram Singh",
        "phone": "+919887654321",
        "company": "Singh Realty Group",
        "source": "Referral",
        "stage": "Proposal",
        "deal_value": 48000,
        "lead_score": 72,
        "tags": ["real-estate", "enterprise", "high-value"],
        "assigned_to": "owner",
        "notes": "Large real estate group with 200+ properties. Wants Nazar for property enquiries, site visit scheduling, and follow-ups.",
        "last_contacted_days_ago": 1,
        "conversations": [
            {"days_ago": 4, "messages": [
                ("inbound", "Arjun from QuickFix told me about your product. We're a real estate group and WhatsApp is our primary sales channel.", "contact"),
                ("outbound", "Hi Vikram! Great to connect — Arjun is one of our star customers. Real estate is a perfect fit for Nazar. How can we help Singh Realty?", "bot"),
                ("inbound", "We get 100+ property enquiries daily. Need AI to qualify leads, schedule site visits, and follow up automatically.", "contact"),
                ("outbound", "Excellent use case! With 100+ daily enquiries, you'd benefit from Enterprise Plan features — AI memory remembers each buyer's preferences, the pipeline tracks deal stages, and broadcasts send personalized property updates. Want a tailored demo?", "bot"),
            ]},
            {"days_ago": 1, "messages": [
                ("inbound", "Had the demo yesterday, very impressed. Send me the Enterprise proposal with annual pricing.", "contact"),
                ("outbound", "Here's your Enterprise proposal, Vikram:\n\n• Enterprise Plan: ₹14,999/month\n• Annual billing: ₹11,999/month (₹1,43,988/year)\n• Includes: Unlimited contacts, API access, custom AI training, dedicated account manager\n• Setup: We'll configure property-specific templates and train the AI on your listings\n\nShall I schedule an onboarding call?", "human"),
            ]},
        ],
    },
    {
        "name": "Sneha Reddy",
        "phone": "+919856781234",
        "company": "WellnessHub Spa",
        "source": "Google",
        "stage": "New",
        "deal_value": 0,
        "lead_score": 30,
        "tags": ["wellness", "new-lead"],
        "assigned_to": None,
        "notes": "",
        "last_contacted_days_ago": 0,
        "conversations": [
            {"days_ago": 0, "messages": [
                ("inbound", "Hello! Can your AI bot help with appointment bookings for a spa?", "contact"),
                ("outbound", "Hi Sneha! Absolutely — spas and wellness centers are a great fit for Nazar. We can automate appointment bookings, send reminders, handle rescheduling, and promote special offers via WhatsApp. How many appointments do you handle daily?", "bot"),
                ("inbound", "Around 20-30 per day. We also want to send post-visit feedback requests.", "contact"),
                ("outbound", "That's perfect! Our Starter Plan handles appointment automation beautifully, and we have a feedback request template built in. Would you like to try a 14-day free trial?", "bot"),
            ]},
        ],
    },
    {
        "name": "Mohammed Faiz",
        "phone": "+919945678901",
        "company": "Crescent Electronics",
        "source": "WhatsApp",
        "stage": "Negotiation",
        "deal_value": 18000,
        "lead_score": 70,
        "tags": ["electronics", "growth-plan"],
        "assigned_to": "owner",
        "notes": "Electronics retailer. Wants Growth Plan for product enquiries and after-sales support.",
        "last_contacted_days_ago": 1,
        "conversations": [
            {"days_ago": 5, "messages": [
                ("inbound", "I have an electronics store. Customers keep asking about product availability and prices on WhatsApp. Need automation.", "contact"),
                ("outbound", "Hi Mohammed! Electronics retail is one of our top use cases. Nazar can handle product queries, share pricing, check availability, and even process orders — all on WhatsApp. How big is your product catalog?", "bot"),
                ("inbound", "About 500 products. We also need warranty support and service center info.", "contact"),
                ("outbound", "With 500 products and after-sales support, the Growth Plan at ₹7,999/month is ideal. We can load your product catalog into the AI's knowledge base so it gives accurate answers. Want to start a trial?", "bot"),
            ]},
            {"days_ago": 1, "messages": [
                ("inbound", "Trial went well! But ₹7,999 is a bit much. Can you do ₹6,000 for the Growth Plan?", "contact"),
                ("outbound", "I appreciate the interest, Mohammed! Our Growth Plan has a lot of value at ₹7,999. For an annual commitment, I can offer ₹6,999/month — that's the best we can do. It includes the full product catalog AI, broadcasts to your customer base, and priority support.", "human"),
                ("inbound", "Let me think about it and get back to you tomorrow.", "contact"),
            ]},
        ],
    },
]


# -----------------------------------------------------------------------
#  SEED FUNCTION
# -----------------------------------------------------------------------

def seed():
    """Seed the database with demo contacts and conversations."""
    existing = list_contacts()
    existing_phones = {c["phone"] for c in existing}
    print(f"\n📊 Existing contacts: {len(existing)}")

    created = 0
    skipped = 0

    for data in CONTACTS:
        phone = normalize_phone(data["phone"])
        if phone in existing_phones:
            print(f"  ⏭  {data['name']} ({phone}) — already exists, skipping")
            skipped += 1
            continue

        # Create contact
        contact = create_contact(
            name=data["name"],
            phone=phone,
            company=data["company"],
            source=data["source"],
            assigned_to=data["assigned_to"],
            tags=data.get("tags", []),
        )
        cid = contact["contact_id"]

        # Move to correct pipeline stage
        if data["stage"] != "New":
            move_stage(cid, data["stage"])

        # Set deal value
        if data["deal_value"]:
            update_contact(cid, deal_value=float(data["deal_value"]))

        # Set lead score
        if data["lead_score"]:
            update_lead_score(cid, data["lead_score"])

        # Set notes
        if data.get("notes"):
            update_contact(cid, notes=data["notes"])

        # Save conversations (with backdated timestamps)
        for conv in data.get("conversations", []):
            days_ago = conv["days_ago"]
            for i, (direction, content, sent_by) in enumerate(conv["messages"]):
                save_message(
                    contact_id=cid,
                    direction=direction,
                    content=content,
                    sent_by=sent_by,
                )

        # Update last_contacted_at / last_replied_at
        days = data.get("last_contacted_days_ago", 0)
        if days > 0:
            update_contact(cid,
                last_contacted_at=ts(days_ago=days),
                last_replied_at=ts(days_ago=days),
            )

        print(f"  ✅ {data['name']} ({phone}) — {data['stage']}, ₹{data['deal_value']:,}")
        created += 1

    # Trigger a sample handoff for Rahul (negotiation contact)
    rahul = get_contact_by_phone(normalize_phone("+919823456789"))
    if rahul:
        try:
            trigger_handoff(
                contact_id=rahul["contact_id"],
                reason="Customer requesting price negotiation — needs human approval",
                triggered_by="ai",
                contact_name=rahul.get("name", ""),
                contact_phone=rahul.get("phone", ""),
                detection_method="ai_intent",
            )
            print(f"\n  🤝 Handoff triggered for Rahul Mehta (negotiation)")
        except Exception as e:
            print(f"\n  ⚠️  Handoff trigger failed for Rahul: {e}")

    print(f"\n✅ Seeding complete! Created: {created}, Skipped: {skipped}")
    print(f"📊 Total contacts now: {len(list_contacts())}")


if __name__ == "__main__":
    seed()
