
import os
import re
import requests

from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from urllib.parse import urlparse
from difflib import SequenceMatcher
from collections import defaultdict

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

load_dotenv()

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
GOOGLE_FACTCHECK_API_KEY = os.getenv(
    "GOOGLE_FACTCHECK_API_KEY", ""
).strip()

TIMEOUT = 25
MAX_CLAIM_LENGTH = 4000

# --------------------------------------------------
# TRUSTED AND EXCLUDED DOMAINS
# --------------------------------------------------

TRUSTED_DOMAINS = {
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "thehindu.com",
    "indianexpress.com",
    "hindustantimes.com",
    "ndtv.com",
    "pib.gov.in",
    "mea.gov.in",
    "mod.gov.in",
    "drdo.gov.in",
    "pmindia.gov.in",
    "who.int",
    "un.org",
    "nature.com",
    "science.org",
    "pubmed.ncbi.nlm.nih.gov",
    "clinicaltrials.gov",
    "theguardian.com",
    "economictimes.indiatimes.com",
    "timesofindia.indiatimes.com",
}

SOCIAL_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "reddit.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "tiktok.com",
    "threads.net",
    "pinterest.com",
    "quora.com",
}

STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were",
    "and", "or", "of", "to", "in", "on", "for",
    "with", "has", "have", "had", "that", "this",
    "it", "by", "from", "as", "at", "be", "been",
    "being", "will", "would", "could", "should",
    "can", "may", "might", "their", "they", "them",
    "its", "he", "she", "his", "her", "we", "our",
    "you", "your", "about", "after", "before",
}

# --------------------------------------------------
# TEXT UTILITIES
# --------------------------------------------------

def clean_text(value, limit=MAX_CLAIM_LENGTH):
    if not isinstance(value, str):
        return ""

    return re.sub(r"\s+", " ", value).strip()[:limit]


def normalize_domain(domain):
    domain = (domain or "").lower().strip()
    domain = domain.removeprefix("www.")
    return domain


def host_of(url):
    try:
        return normalize_domain(urlparse(url).hostname)
    except Exception:
        return ""


def domain_matches(domain, domain_set):
    domain = normalize_domain(domain)

    return any(
        domain == trusted or domain.endswith("." + trusted)
        for trusted in domain_set
    )


def is_social_domain(domain):
    return domain_matches(domain, SOCIAL_DOMAINS)


def is_trusted_domain(domain):
    return domain_matches(domain, TRUSTED_DOMAINS)


def extract_words(text):
    words = re.findall(r"[a-zA-Z0-9]+", (text or "").lower())

    return {
        word for word in words
        if len(word) > 2 and word not in STOP_WORDS
    }


def similarity(text1, text2):
    return SequenceMatcher(
        None,
        (text1 or "").lower(),
        (text2 or "").lower()
    ).ratio()


def claim_relevance(claim, source):
    """
    Check whether a result is meaningfully related to the claim.

    This is a relevance filter, NOT a truth detector.
    """

    claim_words = extract_words(claim)

    source_text = (
        source.get("title", "") + " " +
        source.get("snippet", "")
    )

    source_words = extract_words(source_text)

    if not claim_words or not source_words:
        return 0.0

    overlap = claim_words.intersection(source_words)

    return len(overlap) / len(claim_words)


# --------------------------------------------------
# SOURCE FILTERING
# --------------------------------------------------

def filter_sources(claim, sources):
    accepted = []
    rejected = []

    for source in sources:

        domain = normalize_domain(source.get("domain", ""))

        if not domain:
            rejected.append(source)
            continue

        # Never use social media as independent evidence.
        if is_social_domain(domain):
            rejected.append(source)
            continue

        relevance = claim_relevance(claim, source)

        source["relevance"] = round(relevance, 2)
        source["trusted_domain"] = is_trusted_domain(domain)

        # Avoid unrelated results.
        if relevance < 0.25:
            rejected.append(source)
            continue

        # Reject unknown publishers from the evidence list.
        if not source["trusted_domain"]:
            rejected.append(source)
            continue

        accepted.append(source)

    return accepted, rejected


# --------------------------------------------------
# GOOGLE FACT CHECK API
# --------------------------------------------------

def google_fact_checks(claim):
    if not GOOGLE_FACTCHECK_API_KEY:
        return []

    endpoint = (
        "https://factchecktools.googleapis.com/"
        "v1alpha1/claims:search"
    )

    try:
        response = requests.get(
            endpoint,
            params={
                "query": claim,
                "key": GOOGLE_FACTCHECK_API_KEY,
                "languageCode": "en",
                "pageSize": 10,
            },
            timeout=TIMEOUT,
        )

        response.raise_for_status()
        data = response.json()

        results = []

        for item in data.get("claims", []):

            reviewed_claim = clean_text(
                item.get("text", ""), 1000
            )

            claim_similarity = similarity(
                claim, reviewed_claim
            )

            for review in item.get("claimReview", []):

                publisher = review.get(
                    "publisher", {}
                ).get("name", "Unknown publisher")

                results.append({
                    "claim": reviewed_claim,
                    "publisher": publisher,
                    "title": review.get(
                        "title", "Fact-check review"
                    ),
                    "rating": review.get(
                        "textualRating",
                        "Rating not provided"
                    ),
                    "url": review.get("url", ""),
                    "date": review.get("reviewDate", ""),
                    "claim_similarity": round(
                        claim_similarity, 2
                    ),
                    "assessment": "Related review; verify exact context"
                })

        return results

    except requests.RequestException as error:
        app.logger.error("Google Fact Check API error: %s", error)
        return []


# --------------------------------------------------
# TAVILY SEARCH
# --------------------------------------------------

def tavily_request(query, include_domains=None):

    if not TAVILY_API_KEY:
        return []

    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "advanced",
        "topic": "news",
        "max_results": 10,
        "include_answer": False,
        "include_raw_content": False,
        "exclude_domains": sorted(SOCIAL_DOMAINS),
    }

    if include_domains:
        payload["include_domains"] = include_domains

    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json=payload,
            timeout=TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()
        results = []

        for item in data.get("results", []):

            url = item.get("url", "")
            domain = host_of(url)

            if not domain or is_social_domain(domain):
                continue

            results.append({
                "title": clean_text(
                    item.get("title", "Untitled source"), 300
                ),
                "url": url,
                "domain": domain,
                "snippet": clean_text(
                    item.get("content", ""), 2500
                ),
                "published_date": (
                    item.get("published_date") or ""
                ),
            })

        return results

    except requests.RequestException as error:
        app.logger.error("Tavily API error: %s", error)
        return []


def web_search(claim):

    if not TAVILY_API_KEY:
        return []

    # Search 1: Official and reputable publishers.
    official_query = (
        f'"{claim}" official announcement '
        "government statement confirmation"
    )

    # Search 2: Independent news reporting.
    news_query = (
        f'"{claim}" Reuters AP BBC '
        "news reporting verification"
    )

    official_results = tavily_request(
        official_query,
        include_domains=sorted(TRUSTED_DOMAINS),
    )

    news_results = tavily_request(news_query)

    # Remove duplicate URLs.
    combined = {}
    for source in official_results + news_results:
        if source.get("url"):
            combined[source["url"]] = source

    return list(combined.values())


# --------------------------------------------------
# FACT-CHECK REVIEW ANALYSIS
# --------------------------------------------------

def analyze_fact_checks(fact_checks, claim):

    relevant_reviews = []

    for review in fact_checks:

        # Related search results are not necessarily exact matches.
        if review.get("claim_similarity", 0) < 0.65:
            continue

        relevant_reviews.append(review)

    ratings = defaultdict(list)

    for review in relevant_reviews:

        rating = review.get("rating", "").lower()

        if any(term in rating for term in (
            "false", "pants on fire", "fake", "incorrect"
        )):
            ratings["negative"].append(review)

        elif any(term in rating for term in (
            "true", "correct", "accurate"
        )):
            ratings["positive"].append(review)

        elif any(term in rating for term in (
            "misleading", "partly true", "partially true",
            "half true", "missing context"
        )):
            ratings["mixed"].append(review)

        else:
            ratings["other"].append(review)

    return {
        "relevant": relevant_reviews,
        "positive": ratings["positive"],
        "negative": ratings["negative"],
        "mixed": ratings["mixed"],
        "other": ratings["other"],
    }


# --------------------------------------------------
# EVIDENCE COMPARISON
# --------------------------------------------------

def compare_evidence(sources):

    """
    Search snippets cannot reliably establish whether a claim
    is true or false.

    Therefore, this function reports available evidence and
    does not infer a definitive verdict from keyword matching.
    """

    return {
        "supporting": [],
        "contradicting": [],
        "context": sources,
        "conflict_detected": False,
        "note": (
            "Automatic contradiction detection is not enabled. "
            "The full source articles must be examined before "
            "classifying evidence as supporting or contradicting."
        )
    }


# --------------------------------------------------
# FINAL ASSESSMENT
# --------------------------------------------------

def assess(claim, fact_checks, sources):

    accepted_sources, rejected_sources = filter_sources(
        claim, sources
    )

    review_analysis = analyze_fact_checks(
        fact_checks, claim
    )

    evidence_comparison = compare_evidence(
        accepted_sources
    )

    relevant_reviews = review_analysis["relevant"]

    independent_publishers = {
        normalize_domain(source.get("domain"))
        for source in accepted_sources
    }

    # Never automatically assign TRUE/FALSE from snippets.
    if evidence_comparison["conflict_detected"]:

        verdict = "Conflicting evidence"
        confidence = "low"

        explanation = (
            "Credible sources appear to provide conflicting "
            "information. The original documents and full "
            "reports must be compared before reaching a verdict."
        )

    elif relevant_reviews:

        verdict = "Relevant fact-check reviews found"
        confidence = "medium"

        explanation = (
            f"{len(relevant_reviews)} closely related fact-check "
            "review(s) were found. Their original ratings are "
            "displayed below. A related review is not automatically "
            "a verdict on the exact submitted wording."
        )

    elif len(independent_publishers) >= 2:

        verdict = "Relevant reporting found — verification needed"
        confidence = "medium"

        explanation = (
            f"Relevant reporting was found from "
            f"{len(independent_publishers)} distinct trusted "
            "domains. This demonstrates reporting coverage, "
            "not proof that every detail of the claim is correct. "
            "Read the original articles and official records."
        )

    elif len(independent_publishers) == 1:

        verdict = "Limited evidence found"
        confidence = "low"

        explanation = (
            "Only one relevant trusted publisher was found. "
            "Independent confirmation is needed before "
            "accepting or rejecting the claim."
        )

    else:

        verdict = "Insufficient evidence"
        confidence = "low"

        explanation = (
            "No sufficiently relevant evidence from the "
            "configured trusted publishers was found. "
            "This does not mean the claim is false."
        )

    return {
        "verdict": verdict,
        "confidence": confidence,
        "explanation": explanation,

        "fact_checks": fact_checks,
        "relevant_fact_checks": relevant_reviews,

        "sources": accepted_sources,
        "rejected_source_count": len(rejected_sources),

        "evidence_comparison": evidence_comparison,

        "source_statistics": {
            "total_trusted_sources": len(accepted_sources),
            "independent_publishers": len(independent_publishers),
        },
    }


# --------------------------------------------------
# HOME PAGE
# --------------------------------------------------

@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")


# --------------------------------------------------
# CHECK CLAIM API
# --------------------------------------------------

@app.route("/api/check", methods=["POST"])
def check_claim():

    payload = request.get_json(silent=True) or {}

    claim = clean_text(payload.get("claim"))

    if len(claim) < 12:
        return jsonify({
            "error": "Enter a claim with at least 12 characters."
        }), 400

    # Retrieve fact-check reviews and web sources.
    fact_checks = google_fact_checks(claim)
    raw_sources = web_search(claim)

    # Evaluate the retrieved evidence.
    assessment = assess(
        claim,
        fact_checks,
        raw_sources,
    )

    return jsonify({

        "claim": claim,

        "verdict": assessment["verdict"],
        "confidence": assessment["confidence"],
        "explanation": assessment["explanation"],

        "fact_checks": assessment["fact_checks"],
        "relevant_fact_checks": assessment[
            "relevant_fact_checks"
        ],

        "sources": assessment["sources"],

        "evidence_comparison": assessment[
            "evidence_comparison"
        ],

        "source_statistics": assessment[
            "source_statistics"
        ],

        "rejected_source_count": assessment[
            "rejected_source_count"
        ],

        "coverage": {
            "google_fact_check_api": bool(
                GOOGLE_FACTCHECK_API_KEY
            ),
            "live_web_search": bool(
                TAVILY_API_KEY
            ),
        },

        "disclaimer": (
            "TruthFetch is an automated research assistant, "
            "not a definitive fact-checking authority. Search "
            "results and related fact-check ratings must be "
            "checked against the exact claim, original documents, "
            "dates and context. Insufficient evidence does not "
            "mean false."
        ),
    })


# --------------------------------------------------
# HEALTH CHECK API
# --------------------------------------------------

@app.route("/api/health", methods=["GET"])
def health():

    return jsonify({
        "status": "ok",

        "fact_check_api_configured": bool(
            GOOGLE_FACTCHECK_API_KEY
        ),

        "web_search_configured": bool(
            TAVILY_API_KEY
        ),

        "trusted_domains": len(TRUSTED_DOMAINS),

        "social_domains_excluded": len(SOCIAL_DOMAINS),
    })


# --------------------------------------------------
# ERROR HANDLERS
# --------------------------------------------------

@app.errorhandler(404)
def not_found(error):

    return jsonify({
        "error": "Requested resource was not found."
    }), 404


@app.errorhandler(500)
def internal_error(error):

    app.logger.exception("Internal server error")

    return jsonify({
        "error": "An internal server error occurred."
    }), 500


# --------------------------------------------------
# START APPLICATION
# --------------------------------------------------

if __name__ == "__main__":

    port = int(os.getenv("PORT", "5000"))

    app.run(
        host="127.0.0.1",
        port=port,
        debug=os.getenv("FLASK_DEBUG", "false").lower()
        == "true",
    )
