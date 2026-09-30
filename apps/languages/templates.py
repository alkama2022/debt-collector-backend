"""
Controlled terminology + templates per language.
Variables: {{customer_name}}, {{amount_owed}}, {{outstanding_balance}}, {{invoice}}, {{due_date}}, {{payment}}, {{business_name}}, {{pay_link}}
"""
from string import Template
import re

# ------------------------------------------------------------------
# Terminology dictionary
# ------------------------------------------------------------------
TERMINOLOGY = {
    "en": {
        "amount_owed": "Amount Owed",
        "outstanding_balance": "Outstanding Balance",
        "invoice": "Invoice",
        "due_date": "Due Date",
        "payment": "Payment",
        "pay_money": "Pay money",
        "pay_now": "Pay now",
        "reminder": "Reminder",
        "thank_you": "Thank you",
        "overdue": "Overdue",
        "balance": "Balance",
        "total": "Total",
        "currency": "Naira",
        "greeting": "Hello",
        "dear_customer": "Dear customer",
        "kindly_pay": "Kindly pay",
        "we_appreciate": "We appreciate your prompt payment",
    },
    "ha": {
        "amount_owed": "Adadin Bashi",
        "outstanding_balance": "Ragowar Bashi",
        "invoice": "Rasit",
        "due_date": "Ranar Ƙarshe",
        "payment": "Biyan kuɗi",
        "pay_money": "Biyan kuɗi",
        "pay_now": "Biya yanzu",
        "reminder": "Tunatarwa",
        "thank_you": "Na gode",
        "overdue": "Ya wuce lokaci",
        "balance": "Ragowa",
        "total": "Jimla",
        "currency": "Naira",
        "greeting": "Sannu",
        "dear_customer": "Abokin ciniki mai daraja",
        "kindly_pay": "Don Allah biya",
        "we_appreciate": "Muna godiya da biyan ku akan lokaci",
    },
    "yo": {
        "amount_owed": "Iye Owó Tó Jẹ",
        "outstanding_balance": "Iwọntunwọnsì Owó Tó Kù",
        "invoice": "Ìwé Owó",
        "due_date": "Ọjọ́ Tó Yẹ",
        "payment": "Owo sisan",
        "pay_money": "Owo sisan",
        "pay_now": "Sanwo nisisiyi",
        "reminder": "Ìránnilétí",
        "thank_you": "E se gan",
        "overdue": "Tó ti kọjá ọjọ́",
        "balance": "Iwọntunwọnsì",
        "total": "Lápapọ̀",
        "currency": "Naira",
        "greeting": "Bawo",
        "dear_customer": "Onibara ọwọn",
        "kindly_pay": "Jọwọ sanwo",
        "we_appreciate": "A dupẹ fun sisanwo rẹ ni kiakia",
    },
    "ig": {
        "amount_owed": "Ego Ji",
        "outstanding_balance": "Nkwụsị Ego Fọdụrụ",
        "invoice": "Akwụkwọ Ụgwọ",
        "due_date": "Ụbọchị Ruru",
        "payment": "Ịkwụ ụgwọ",
        "pay_money": "Ịkwụ ụgwọ",
        "pay_now": "Kwụọ ụgwọ ugbu a",
        "reminder": "Ihe Ncheta",
        "thank_you": "Daalụ",
        "overdue": "Agafeela oge",
        "balance": "Nkwụsị",
        "total": "Mgbakọta",
        "currency": "Naira",
        "greeting": "Ndewo",
        "dear_customer": "Ezigbo onye ahịa",
        "kindly_pay": "Biko kwụọ ụgwọ",
        "we_appreciate": "Anyị nwere ekele maka ịkwụ ụgwọ gị ngwa ngwa",
    },
    "pcm": {
        "amount_owed": "Money Wey You Owe",
        "outstanding_balance": "Balance Wey Remain",
        "invoice": "Invoice",
        "due_date": "Due Date",
        "payment": "Pay money",
        "pay_money": "Pay money",
        "pay_now": "Pay now now",
        "reminder": "Reminder",
        "thank_you": "Thank you",
        "overdue": "Don overdue",
        "balance": "Balance",
        "total": "Total",
        "currency": "Naira",
        "greeting": "How far",
        "dear_customer": "My correct customer",
        "kindly_pay": "Abeg pay",
        "we_appreciate": "We thank you say you pay quick quick",
    },
}

# ------------------------------------------------------------------
# Templates per language — natural, human, not robotic
# Each key holds 3-4 variants. render_template picks one randomly (stable per call)
# Tone: warm, respectful, concise, Nigerian business etiquette.
# ------------------------------------------------------------------
import random as _random

NATURAL_VARIANTS = {
    "en": {
        "reminder": [
            "Hi {{customer_name}} — hope you're well! Just a friendly nudge from {{business_name}}: your balance of {{currency}} {{amount_owed}} for {{invoice}} {{invoice_number}} is due {{due_date_value}}. You can pay securely here: {{pay_link}} — takes 30 seconds. Thanks so much! 🙏",
            "{{greeting}} {{customer_name}}, trust you're doing great. Quick reminder from {{business_name}} — {{currency}} {{amount_owed}} is due on {{due_date_value}} ({{invoice}} {{invoice_number}}). Pay now: {{pay_link}}. We really appreciate you!",
            "Hello {{customer_name}}! {{business_name}} here. Just letting you know {{currency}} {{amount_owed}} is due {{due_date_value}}. Here's your secure link: {{pay_link}}. Let us know if you need a payment plan — happy to help. {{thank_you}}!",
        ],
        "overdue": [
            "Hi {{customer_name}}, I know things get busy — your payment of {{currency}} {{amount_owed}} was due {{due_date_value}} and is now overdue. No worries, you can clear it in a moment here: {{pay_link}}. Need more time? Just reply and we'll arrange a plan. Thanks for choosing {{business_name}}.",
            "{{greeting}} {{customer_name}}, your balance of {{currency}} {{amount_owed}} ({{invoice}} {{invoice_number}}) slipped past {{due_date_value}}. You can settle now: {{pay_link}} — or tell us what works for you and we'll sort it together.",
        ],
        "negotiation": [
            "I understand, {{customer_name}} — thanks for letting us know. We can split {{currency}} {{amount_owed}} into smaller parts. Would you prefer to pay in 2 installments, or tell me a date that works for you? Here's your link anytime: {{pay_link}}.",
            "No problem at all, {{customer_name}}. Many customers do this — we can spread {{currency}} {{amount_owed}} over the next few weeks. What amount can you manage this week? Pay here when ready: {{pay_link}}",
        ],
        "promise": [
            "Perfect, thanks {{customer_name}}! I've noted you'll pay {{currency}} {{amount_owed}} on {{due_date_value}}. I'll send a gentle reminder that morning, and your link will be ready: {{pay_link}}. We appreciate your commitment!",
            "Great — so {{due_date_value}} for {{currency}} {{amount_owed}}, {{customer_name}}? Noted! You'll get a reminder, and you can always pay early here: {{pay_link}}. Thank you!",
        ],
        "receipt": [
            "{{thank_you}} {{customer_name}}! We've received your payment of {{currency}} {{amount_owed}} for {{invoice}} {{invoice_number}}. Your remaining balance is {{currency}} {{outstanding_balance}}. We're grateful — receipt sent!",
            "Received with thanks, {{customer_name}}! {{currency}} {{amount_owed}} for {{invoice}} {{invoice_number}} is confirmed. Balance left: {{currency}} {{outstanding_balance}}. {{thank_you}}!",
        ],
        "human_handoff": [
            "Thanks for sharing that, {{customer_name}}. Let me connect you with our team at {{business_name}} — they'll pick this up within a few hours and get you sorted. Your link stays active: {{pay_link}}",
        ],
    },
    "ha": {
        "reminder": [
            "{{greeting}} {{customer_name}}, ina fatan kana lafiya! Tunatarwa ce daga {{business_name}}: biyan ku na {{currency}} {{amount_owed}} zai cika {{due_date_value}} ({{invoice}} {{invoice_number}}). Ka biya anan cikin sauƙi: {{pay_link}}. {{thank_you}}!",
            "Sannu {{customer_name}} — {{business_name}} ne. Don Allah ka tuna {{currency}} {{amount_owed}} zai wuce {{due_date_value}}. Ga link ɗin biya: {{pay_link}}.",
        ],
        "overdue": ["{{greeting}} {{customer_name}}, biyan ku na {{currency}} {{amount_owed}} ya wuce {{due_date_value}} amma babu damuwa — ka biya yanzu: {{pay_link}}. Idan kana bukatar lokaci, ka gaya mana."],
        "receipt": ["{{thank_you}} {{customer_name}}! Mun karɓi {{currency}} {{amount_owed}} don {{invoice}} {{invoice_number}}. Ragowar kuɗin ka {{currency}} {{outstanding_balance}} ne."],
    },
    "yo": {
        "reminder": [
            "{{greeting}} {{customer_name}}, bawo ni o? Ẹ ranti owo {{currency}} {{amount_owed}} to maabo ni {{due_date_value}} lati ọdọ {{business_name}} ({{invoice}} {{invoice_number}}). Sanwo nibi: {{pay_link}}. {{thank_you}}!",
        ],
        "overdue": ["{{greeting}} {{customer_name}}, owo {{currency}} {{amount_owed}} ti kọja {{due_date_value}}, ṣugbọn ko si wahala — sanwo nisisiyi: {{pay_link}}"],
        "receipt": ["{{thank_you}} {{customer_name}}! A ti gba {{currency}} {{amount_owed}} fun {{invoice}} {{invoice_number}}. Iwọntunwọnsì to kù ni {{currency}} {{outstanding_balance}}."],
    },
    "ig": {
        "reminder": [
            "{{greeting}} {{customer_name}}, kedu ka ị mere? Ihe ncheta sitere na {{business_name}}: {{currency}} {{amount_owed}} ga-eru {{due_date_value}} ({{invoice}} {{invoice_number}}). Kwụọ ebe a: {{pay_link}}. {{thank_you}}!",
        ],
        "overdue": ["{{greeting}} {{customer_name}}, ụgwọ {{currency}} {{amount_owed}} agafeela {{due_date_value}} — enweghị nsogbu, kwụọ ugbu a: {{pay_link}}"],
        "receipt": ["{{thank_you}} {{customer_name}}! Anyị anatawo {{currency}} {{amount_owed}} maka {{invoice}} {{invoice_number}}. Ihe fọdụrụ bụ {{currency}} {{outstanding_balance}}."],
    },
    "pcm": {
        "reminder": [
            "{{greeting}} {{customer_name}}! Na {{business_name}} be this. Just dey remind you say {{currency}} {{amount_owed}} go due for {{due_date_value}} ({{invoice}} {{invoice_number}}). Abeg pay for here: {{pay_link}}. We appreciate you well well! 🙏",
            "How far {{customer_name}}! Your balance na {{currency}} {{amount_owed}} wey go due {{due_date_value}}. Pay sharp sharp for here: {{pay_link}}. If you need small small payment, we fit arrange am.",
        ],
        "overdue": ["{{greeting}} {{customer_name}}, your {{currency}} {{amount_owed}} don overdue since {{due_date_value}} but no wahala — you fit pay now now: {{pay_link}}. You need more time? Just tell us."],
        "receipt": ["{{thank_you}} {{customer_name}}! We don collect your {{currency}} {{amount_owed}} for {{invoice}} {{invoice_number}}. Balance wey remain na {{currency}} {{outstanding_balance}} — God bless!"],
        "negotiation": ["No wahala {{customer_name}}, we understand. We fit break {{currency}} {{amount_owed}} to two times. How much you fit pay this week? Link dey here: {{pay_link}}"],
    },
}

# Backwards-compat: old TEMPLATES now delegates to NATURAL_VARIANTS first variant
TEMPLATES = {
    lang: {k: v[0] for k, v in cats.items()}
    for lang, cats in NATURAL_VARIANTS.items()
}

# Future languages can be added as inactive entries: e.g. ff (Fulfulde), kr (Kanuri), tiv etc.
# To add: insert row in Language with active=False, then add TERMINOLOGY[code] and TEMPLATES[code] without code changes to router.


def get_terminology(lang_code: str, key: str, fallback: str = "en") -> str:
    """Lookup terminology with fallback."""
    if lang_code in TERMINOLOGY and key in TERMINOLOGY[lang_code]:
        return TERMINOLOGY[lang_code][key]
    if fallback in TERMINOLOGY and key in TERMINOLOGY[fallback]:
        return TERMINOLOGY[fallback][key]
    return key


def _pick_variant(lang_code: str, template_name: str) -> str:
    cats = NATURAL_VARIANTS.get(lang_code) or NATURAL_VARIANTS.get("en")
    variants = cats.get(template_name) if cats else None
    if not variants:
        # fallback to old TEMPLATES
        lang = lang_code if lang_code in TEMPLATES else "en"
        return TEMPLATES.get(lang, TEMPLATES["en"]).get(template_name, "{{greeting}} {{customer_name}}")
    return _random.choice(variants)

def render_template(template_name: str, lang_code: str, context: dict, variant_idx: int | None = None) -> str:
    """Render natural template. Picks random variant unless variant_idx given."""
    lang = lang_code if lang_code in NATURAL_VARIANTS else "en"
    if variant_idx is not None:
        cats = NATURAL_VARIANTS.get(lang, NATURAL_VARIANTS["en"])
        variants = cats.get(template_name, [])
        tmpl_str = variants[variant_idx % len(variants)] if variants else _pick_variant(lang, template_name)
    else:
        tmpl_str = _pick_variant(lang, template_name)
    # Merge terminology into context as defaults
    merged = {}
    term = TERMINOLOGY.get(lang, TERMINOLOGY["en"])
    for k, v in term.items():
        merged[k] = v
    merged.setdefault("currency", "NGN")
    merged.setdefault("business_name", "CollectNaija")
    merged.setdefault("pay_link", "https://pay.collectnaija.com")
    merged.setdefault("invoice_number", "")
    merged.setdefault("due_date_value", "")
    merged.setdefault("outstanding_balance", merged.get("outstanding_balance", ""))
    merged.setdefault("customer_name", "Customer")
    if context:
        for k, v in context.items():
            if v is not None:
                merged[k] = str(v)
    def replacer(m):
        key = m.group(1).strip()
        return merged.get(key, m.group(0))
    rendered = re.sub(r"\{\{\s*(\w+)\s*\}\}", replacer, tmpl_str)
    return rendered

def render_natural(template_name: str, lang_code: str, context: dict, tone: str = "warm") -> str:
    """Explicit natural entry — tone warm/professional/urgent."""
    return render_template(template_name, lang_code, context)
