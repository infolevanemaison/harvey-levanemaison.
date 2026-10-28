"""Scoring a creator for a women's fashion brand (audience 35-65, Spain/France).

Deterministic and explainable: every point comes with a reason a person can
check, and a missing number is said to be missing instead of guessed. The
score ranks who to look at first; it never decides who is contacted.

Four parts, 100 points:
- audience relevance  35  women, aged 35-65, in the target countries
- engagement          25  interactions per post against her size's norm
- authenticity        25  starts full; red flags take points off
- cost efficiency     15  estimated cost per interaction

Benchmarks are rules of thumb from public industry reports, not facts about
any one creator. Cost is an estimate unless she quoted a fee.
"""

from dataclasses import asdict, dataclass, field

PLATFORMS = ("instagram", "tiktok", "youtube", "blog")

# Interactions per post / followers that count as healthy, by size.
# Instagram engagement falls as accounts grow; TikTok and YouTube are
# measured on views, so their norms are views-based (see _engagement_rate).
ER_BENCHMARK = {
    "instagram": ((10_000, 0.035), (50_000, 0.022), (150_000, 0.015), (None, 0.010)),
    "tiktok": ((10_000, 0.080), (50_000, 0.060), (150_000, 0.050), (None, 0.040)),
    "youtube": ((10_000, 0.050), (50_000, 0.040), (150_000, 0.030), (None, 0.020)),
}

# Rough price per post per 1,000 followers in Spain/France fashion,
# (low, high) in euros. Used only when she hasn't quoted a fee.
FEE_PER_1K_FOLLOWERS = {"instagram": (5.0, 12.0), "tiktok": (4.0, 10.0),
                        "youtube": (10.0, 25.0)}
# Share of followers a post typically reaches (organic).
REACH_RATE = {"instagram": 0.20, "tiktok": 0.35, "youtube": 0.25}

PRIORITY, REVIEW, DISCARD = "prioritaria", "revisar", "descartar"
PERMITTED_CHANNELS = ("colaboraciones", "plataforma", "formulario", "agencia")
# Not enough data to judge: neither audience nor engagement is known yet.
INCOMPLETE = "faltan datos"


@dataclass
class Creator:
    handle: str
    platform: str = "instagram"
    display_name: str = ""
    country: str = ""                      # ES, FR, ...
    language: str = ""                     # es, fr
    profile_url: str = ""
    followers: int = 0
    avg_likes: float = 0.0                 # per recent post
    avg_comments: float = 0.0
    avg_views: float = 0.0                 # TikTok / YouTube / Reels
    posts_last_30d: int = 0
    sponsored_posts_last_30d: int = 0
    follower_growth_30d_pct: float | None = None
    audience_female_pct: float | None = None       # from her media kit / insights
    audience_35_65_pct: float | None = None
    audience_target_country_pct: float | None = None
    comment_quality: int | None = None     # 1-5, a person's judgement of real comments
    content_notes: str = ""                # what she posts, in a person's words
    pro_contact_email: str = ""            # the professional contact SHE publishes
    pro_contact_source: str = ""           # where it is published (URL)
    quoted_fee_eur: float | None = None    # her own quote, if she gave one
    # What kind of channel pro_contact_source is. Only a channel she opens
    # for brand proposals may be used (LSSI art. 21 needs prior consent for
    # commercial e-mail): "colaboraciones" (an e-mail or page she publishes
    # for collaborations), "plataforma", "formulario", "agencia". A general
    # contact address is "general" and is not enough.
    channel_kind: str = ""
    stats_verified: bool = False           # numbers from her media kit, insights or a platform's audited data
    stats_source: str = ""                 # where the numbers come from
    accepts: str = ""                      # what she publicly accepts: comision, producto, pago (comma-separated)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Score:
    total: int
    verdict: str
    audience: float
    engagement: float
    authenticity: float
    cost: float
    engagement_rate: float | None
    estimated_fee_eur: tuple[float, float] | None
    estimated_reach: int
    contactable: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # How she can be reached for a collaboration: "email", "canal" (a
    # platform, form or agency she publishes for brand proposals) or "".
    channel: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def channel_of(c: Creator) -> str:
    """"email" (an e-mail she publishes for collaborations), "canal" (a
    platform, form, agency or collaborations page she opens for brands) or
    "" (none that may be used)."""
    kind = (c.channel_kind or "").strip().lower()
    if not c.pro_contact_source or kind not in PERMITTED_CHANNELS:
        return ""
    return "email" if kind == "colaboraciones" and c.pro_contact_email else "canal"


def viable_terms(c: Creator) -> list[str]:
    """The zero-budget formulas she publicly accepts (commission, product)."""
    said = {t.strip().lower() for t in (c.accepts or "").replace(";", ",").split(",")}
    return [t for t in ("comision", "producto") if t in said]


def _benchmark(platform: str, followers: int) -> float:
    for limit, rate in ER_BENCHMARK.get(platform, ER_BENCHMARK["instagram"]):
        if limit is None or followers < limit:
            return rate
    return 0.01


def _engagement_rate(c: Creator) -> float | None:
    """Interactions per post over followers (Instagram), or over views
    where views are the honest base (TikTok, YouTube)."""
    interactions = (c.avg_likes or 0) + (c.avg_comments or 0)
    if c.platform in ("tiktok", "youtube") and c.avg_views:
        return interactions / c.avg_views
    if c.followers > 0 and interactions > 0:
        return interactions / c.followers
    return None


def _pct_points(value: float | None, full_at: float, points: float) -> float:
    if value is None:
        return 0.0
    return round(points * max(0.0, min(1.0, value / full_at)), 1)


def estimate_fee(c: Creator) -> tuple[float, float] | None:
    if c.quoted_fee_eur is not None:
        return (float(c.quoted_fee_eur), float(c.quoted_fee_eur))
    if c.followers <= 0 or c.platform not in FEE_PER_1K_FOLLOWERS:
        # No public rule of thumb for blogs: ask her rate instead of guessing.
        return None
    low, high = FEE_PER_1K_FOLLOWERS.get(c.platform, FEE_PER_1K_FOLLOWERS["instagram"])
    k = c.followers / 1000
    return (round(k * low), round(k * high))


def estimated_reach(c: Creator) -> int:
    if c.avg_views:
        return int(c.avg_views)
    return int(c.followers * REACH_RATE.get(c.platform, 0.2))


def score_creator(c: Creator, countries=("ES", "FR"), min_followers: int = 2_000,
                  max_followers: int = 150_000) -> Score:
    reasons: list[str] = []
    warnings: list[str] = []

    # ── Audience relevance (35) ──
    female = _pct_points(c.audience_female_pct, 80, 12)
    age = _pct_points(c.audience_35_65_pct, 55, 15)
    place = _pct_points(c.audience_target_country_pct, 60, 8)
    audience = female + age + place
    if c.audience_female_pct is None or c.audience_35_65_pct is None:
        warnings.append("Sin datos de audiencia (sexo/edad): pídele su media kit o "
                        "capturas de estadísticas antes de decidir.")
    else:
        reasons.append(f"Audiencia: {c.audience_female_pct:.0f}% mujeres, "
                       f"{c.audience_35_65_pct:.0f}% de 35-65 años.")
    if c.audience_target_country_pct is not None:
        reasons.append(f"{c.audience_target_country_pct:.0f}% de su audiencia en el país objetivo.")

    # ── Engagement (25) ──
    rate = _engagement_rate(c)
    bench = _benchmark(c.platform, c.followers)
    if rate is None:
        engagement = 0.0
        warnings.append("Sin datos de interacción: anota likes y comentarios medios de "
                        "sus últimas 9-12 publicaciones.")
    else:
        engagement = round(25 * min(1.0, rate / bench), 1)
        reasons.append(f"Interacción {rate:.1%} frente a {bench:.1%} habitual para su tamaño.")
    if c.posts_last_30d and c.posts_last_30d < 4:
        engagement = round(engagement * 0.7, 1)
        warnings.append(f"Publica poco ({c.posts_last_30d} en 30 días).")

    # ── Authenticity (25, red flags subtract) ──
    authenticity = 25.0
    if rate is not None and rate > bench * 3:
        authenticity -= 6
        warnings.append("Interacción anormalmente alta: revisa si hay grupos de "
                        "interacción o sorteos inflando los números.")
    if rate is not None and rate < bench * 0.3:
        authenticity -= 10
        warnings.append("Interacción muy baja para sus seguidores: posible audiencia "
                        "comprada o inactiva.")
    if c.avg_likes and c.avg_comments / max(c.avg_likes, 1) < 0.005:
        authenticity -= 5
        warnings.append("Casi no hay comentarios para tantos likes.")
    if c.follower_growth_30d_pct is not None and c.follower_growth_30d_pct > 25:
        authenticity -= 8
        warnings.append(f"Crecimiento brusco de seguidores ({c.follower_growth_30d_pct:.0f}% "
                        "en 30 días) sin explicación visible.")
    if c.posts_last_30d and c.sponsored_posts_last_30d / c.posts_last_30d > 0.5:
        authenticity -= 5
        warnings.append("Más de la mitad de sus publicaciones son patrocinadas.")
    if c.comment_quality is not None:
        if c.comment_quality <= 2:
            authenticity -= 6
            warnings.append("Comentarios de baja calidad (emojis o frases genéricas).")
        elif c.comment_quality >= 4:
            reasons.append("Comentarios reales y conversación con su comunidad.")
    authenticity = max(0.0, authenticity)

    # ── Cost efficiency (15) ──
    # Cost per interaction, not per follower: an estimated fee grows with
    # followers whoever she is, so only real interactions tell an efficient
    # account from an inflated one.
    fee = estimate_fee(c)
    reach = estimated_reach(c)
    interactions = (c.avg_likes or 0) + (c.avg_comments or 0)
    if fee and interactions:
        mid = (fee[0] + fee[1]) / 2
        cpe = mid / interactions
        # Full points at 0.10 EUR per interaction or less, none at 1 EUR or more.
        cost = round(15 * max(0.0, min(1.0, (1.0 - cpe) / 0.9)), 1)
        label = "tarifa indicada por ella" if c.quoted_fee_eur is not None else "estimación orientativa"
        reasons.append(f"Coste por publicación {fee[0]:.0f}-{fee[1]:.0f} EUR ({label}); "
                       f"~{cpe:.2f} EUR por interacción; alcance estimado {reach} personas.")
    else:
        cost = 0.0
        warnings.append("No se puede estimar el coste sin interacciones o tarifa.")

    total = int(round(audience + engagement + authenticity + cost))

    # ── Hard rules: these decide the verdict whatever the score ──
    kind = (c.channel_kind or "").strip().lower()
    channel = channel_of(c)
    contactable = channel == "email"
    if channel == "email":
        reasons.append(f"Email publicado por ella para colaboraciones ({c.pro_contact_source}).")
    elif channel == "canal":
        reasons.append(f"Canal de colaboraciones permitido ({kind}): {c.pro_contact_source}. "
                       "Se le escribe solo por esa vía.")
    elif kind == "general":
        warnings.append("Solo consta un contacto general: no basta para una propuesta comercial "
                        "(LSSI art. 21). Hay que encontrar un canal que ella abra para colaboraciones.")
    elif c.pro_contact_source:
        warnings.append("Canal sin clasificar: indica si es de colaboraciones, plataforma, "
                        "formulario, agencia o general antes de usarlo.")
    else:
        warnings.append("No consta un canal de colaboraciones publicado por ella: no se le "
                        "escribe. Primero hay que verificar uno (web, formulario, agencia, plataforma).")
    if c.stats_verified:
        reasons.append(f"Estadísticas verificadas ({c.stats_source or 'fuente anotada'}).")
    elif c.followers or c.avg_likes:
        warnings.append("Cifras sin verificar: pide su media kit o capturas de estadísticas.")
    disqualified = []
    if countries and c.country and c.country.upper() not in {x.upper() for x in countries}:
        disqualified.append(f"país {c.country} fuera del objetivo")
    if c.followers and c.followers > max_followers:
        # Never discarded for size alone: big accounts usually cost more,
        # which the ranking reflects, but some take commission or product.
        warnings.append(f"Cuenta grande ({c.followers} seguidores): coste probablemente alto; "
                        "solo interesa si acepta comisión o producto.")
    elif c.followers and c.followers < min_followers:
        # Small is not bad: a small, well-matched audience can sell better and
        # cost less. Say it, don't discard it.
        warnings.append(f"Cuenta pequeña ({c.followers} seguidores): alcance limitado; "
                        "interesa si su audiencia encaja y el coste es bajo.")
    if c.audience_target_country_pct is not None and c.audience_target_country_pct < 20:
        disqualified.append(f"solo {c.audience_target_country_pct:.0f}% de su audiencia en España/Francia")
    if c.platform not in PLATFORMS:
        disqualified.append(f"plataforma {c.platform!r} no contemplada")

    if disqualified:
        verdict = DISCARD
        reasons.insert(0, "Descartada: " + "; ".join(disqualified) + ".")
    elif rate is None and (c.audience_female_pct is None or c.audience_35_65_pct is None):
        # Authenticity starts full, so an empty profile would otherwise score
        # ~25 and read as "discard". Missing is not bad: say it's missing.
        verdict = INCOMPLETE
        reasons.insert(0, "Sin interacción ni audiencia anotadas: todavía no se puede valorar.")
    elif total >= 70:
        verdict = PRIORITY
    elif total >= 50:
        verdict = REVIEW
    else:
        verdict = DISCARD

    return Score(total=total, verdict=verdict, audience=round(audience, 1),
                 engagement=engagement, authenticity=authenticity, cost=cost,
                 engagement_rate=rate, estimated_fee_eur=fee, estimated_reach=reach,
                 contactable=contactable, reasons=reasons, warnings=warnings, channel=channel)
