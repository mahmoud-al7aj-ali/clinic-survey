import os
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

QUESTION_TYPE_RATING = "rating"
QUESTION_TYPE_YES_NO = "yes_no"

RATING_LABELS = {
    "very_important": "مهمة جداً",
    "important": "مهمة",
    "nice_to_have": "مفيدة",
    "not_needed": "غير ضرورية",
}

YES_NO_LABELS = {
    "yes": "نعم",
    "no": "لا",
}

ANSWER_LABELS = {**RATING_LABELS, **YES_NO_LABELS}


def feature_question_type(feature):
    return feature.get("question_type") or QUESTION_TYPE_RATING


def is_valid_answer(feature, value):
    qtype = feature_question_type(feature)
    if qtype == QUESTION_TYPE_YES_NO:
        return value in YES_NO_LABELS
    return value in RATING_LABELS


def answer_label(value):
    return ANSWER_LABELS.get(value, value)

RATING_WEIGHTS = {
    "very_important": 4,
    "important": 3,
    "nice_to_have": 2,
    "not_needed": 1,
}

_client: Optional[Client] = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_KEY must be set (see .env.example)"
            )
        _client = create_client(url, key)
    return _client


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    get_supabase()


def survey_count():
    sb = get_supabase()
    res = sb.table("surveys").select("id", count="exact").execute()
    return res.count or 0


def clear_all_data():
    sb = get_supabase()
    sb.table("surveys").delete().gte("id", 0).execute()
    sb.table("admin_users").delete().gte("id", 0).execute()


def normalize_phone(phone):
    return "".join(c for c in (phone or "") if c.isdigit())


def find_existing_response(survey_id, phone, email=None):
    norm_phone = normalize_phone(phone)
    norm_email = (email or "").strip().lower()
    by_phone = None
    by_email = None
    sb = get_supabase()
    rows = (
        sb.table("responses")
        .select("id, phone, email")
        .eq("survey_id", survey_id)
        .execute()
        .data
        or []
    )
    for row in rows:
        if norm_phone and normalize_phone(row.get("phone")) == norm_phone:
            by_phone = row["id"]
        row_email = (row.get("email") or "").strip().lower()
        if norm_email and row_email and row_email == norm_email:
            by_email = row["id"]
    if by_phone and by_email and by_phone != by_email:
        return "conflict"
    return by_phone or by_email


def email_used_by_other(survey_id, email, exclude_response_id):
    norm_email = (email or "").strip().lower()
    if not norm_email:
        return False
    sb = get_supabase()
    rows = (
        sb.table("responses")
        .select("id, email")
        .eq("survey_id", survey_id)
        .neq("id", exclude_response_id)
        .execute()
        .data
        or []
    )
    return any((r.get("email") or "").strip().lower() == norm_email for r in rows)


def get_active_survey():
    sb = get_supabase()
    rows = (
        sb.table("surveys")
        .select("*")
        .eq("is_active", True)
        .order("id", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def survey_structure(survey_id):
    sb = get_supabase()
    sections = (
        sb.table("sections")
        .select("*")
        .eq("survey_id", survey_id)
        .order("page_order")
        .execute()
        .data
        or []
    )
    structure = []
    for section in sections:
        groups = (
            sb.table("feature_groups")
            .select("*")
            .eq("section_id", section["id"])
            .order("sort_order")
            .order("id")
            .execute()
            .data
            or []
        )
        group_list = []
        for group in groups:
            features = (
                sb.table("features")
                .select("*")
                .eq("group_id", group["id"])
                .eq("is_active", True)
                .order("sort_order")
                .order("feature_num")
                .execute()
                .data
                or []
            )
            if features:
                group_list.append({"group": group, "features": features})
        if group_list:
            structure.append({"section": section, "groups": group_list})
    return structure


def count_active_features(survey_id):
    structure = survey_structure(survey_id)
    return sum(len(g["features"]) for page in structure for g in page["groups"])


def get_survey_features(survey_id):
    sb = get_supabase()
    sections = (
        sb.table("sections").select("id").eq("survey_id", survey_id).execute().data or []
    )
    if not sections:
        return []
    section_ids = [s["id"] for s in sections]
    groups = (
        sb.table("feature_groups")
        .select("id")
        .in_("section_id", section_ids)
        .execute()
        .data
        or []
    )
    if not groups:
        return []
    group_ids = [g["id"] for g in groups]
    return (
        sb.table("features")
        .select("id, feature_num")
        .in_("group_id", group_ids)
        .eq("is_active", True)
        .execute()
        .data
        or []
    )


def save_survey_response(
    survey_id,
    doctor,
    clinic,
    phone,
    email,
    notes,
    wants_updates,
    answers,
    by_num,
):
    existing_id = find_existing_response(survey_id, phone, email or None)
    if existing_id == "conflict":
        return None, "conflict", False

    sb = get_supabase()
    now = utc_now()
    payload = {
        "doctor_name": doctor,
        "clinic_name": clinic,
        "phone": phone,
        "email": email or None,
        "notes": notes,
        "wants_updates": bool(wants_updates),
        "submitted_at": now,
    }

    if existing_id:
        if email and email_used_by_other(survey_id, email, existing_id):
            return None, "email_taken", False
        sb.table("responses").update(payload).eq("id", existing_id).eq(
            "survey_id", survey_id
        ).execute()
        sb.table("response_answers").delete().eq("response_id", existing_id).execute()
        response_id = existing_id
        updated = True
    else:
        payload["survey_id"] = survey_id
        row = sb.table("responses").insert(payload).execute().data[0]
        response_id = row["id"]
        updated = False

    answer_rows = [
        {
            "response_id": response_id,
            "feature_id": by_num[str(num)],
            "rating": rating,
        }
        for num, rating in answers.items()
    ]
    if answer_rows:
        sb.table("response_answers").insert(answer_rows).execute()

    return response_id, None, updated


def get_admin_user(username):
    sb = get_supabase()
    rows = (
        sb.table("admin_users")
        .select("*")
        .eq("username", username)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def count_responses(survey_id):
    sb = get_supabase()
    res = (
        sb.table("responses")
        .select("id", count="exact")
        .eq("survey_id", survey_id)
        .execute()
    )
    return res.count or 0


def recent_responses(survey_id, limit=10):
    sb = get_supabase()
    return (
        sb.table("responses")
        .select("id, doctor_name, clinic_name, submitted_at")
        .eq("survey_id", survey_id)
        .order("submitted_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )


def rating_counts_for_survey(survey_id):
    sb = get_supabase()
    responses = (
        sb.table("responses").select("id").eq("survey_id", survey_id).execute().data
        or []
    )
    if not responses:
        return {}
    response_ids = [r["id"] for r in responses]
    answers = (
        sb.table("response_answers")
        .select("rating")
        .in_("response_id", response_ids)
        .execute()
        .data
        or []
    )
    counts = {}
    for a in answers:
        counts[a["rating"]] = counts.get(a["rating"], 0) + 1
    return counts


def feature_rating_rankings(survey_id, sort_by="score"):
    sb = get_supabase()
    sections = (
        sb.table("sections").select("id, page_title").eq("survey_id", survey_id).execute().data
        or []
    )
    section_map = {s["id"]: s for s in sections}
    section_ids = list(section_map.keys())
    if not section_ids:
        return []

    groups = (
        sb.table("feature_groups")
        .select("id, title, section_id")
        .in_("section_id", section_ids)
        .execute()
        .data
        or []
    )
    group_map = {g["id"]: g for g in groups}
    group_ids = list(group_map.keys())
    if not group_ids:
        return []

    features = (
        sb.table("features")
        .select("id, feature_num, title, description, group_id, question_type")
        .in_("group_id", group_ids)
        .eq("is_active", True)
        .execute()
        .data
        or []
    )

    responses = (
        sb.table("responses").select("id").eq("survey_id", survey_id).execute().data or []
    )
    response_ids = [r["id"] for r in responses]
    answers = []
    if response_ids:
        answers = (
            sb.table("response_answers")
            .select("feature_id, rating")
            .in_("response_id", response_ids)
            .execute()
            .data
            or []
        )

    votes_by_feature = {}
    for a in answers:
        fid = a["feature_id"]
        if fid not in votes_by_feature:
            votes_by_feature[fid] = []
        votes_by_feature[fid].append(a["rating"])

    items = []
    for f in features:
        if feature_question_type(f) == QUESTION_TYPE_YES_NO:
            continue
        g = group_map.get(f["group_id"], {})
        sec = section_map.get(g.get("section_id"), {})
        ratings = votes_by_feature.get(f["id"], [])
        cnt = {k: 0 for k in RATING_LABELS}
        for r in ratings:
            if r in cnt:
                cnt[r] += 1
        total = len(ratings)
        if total:
            score = sum(RATING_WEIGHTS.get(r, 0) for r in ratings) / total
        else:
            score = None
        items.append(
            {
                "id": f["id"],
                "feature_num": f["feature_num"],
                "title": f["title"],
                "description": f.get("description"),
                "group_title": g.get("title"),
                "page_title": sec.get("page_title"),
                "cnt_very_important": cnt["very_important"],
                "cnt_important": cnt["important"],
                "cnt_nice_to_have": cnt["nice_to_have"],
                "cnt_not_needed": cnt["not_needed"],
                "total_votes": total,
                "priority_score": round(score, 2) if score is not None else None,
                "pct_very_important": (
                    round(100 * cnt["very_important"] / total, 1) if total else 0
                ),
            }
        )

    if sort_by == "very_important":
        items.sort(
            key=lambda x: (
                -x["cnt_very_important"],
                -(x["priority_score"] or 0),
                x["feature_num"],
            )
        )
    elif sort_by == "num":
        items.sort(key=lambda x: x["feature_num"])
    else:
        items.sort(
            key=lambda x: (
                -(x["priority_score"] or 0),
                -x["cnt_very_important"],
                x["feature_num"],
            )
        )
    return items


def yes_no_question_stats(survey_id):
    sb = get_supabase()
    sections = (
        sb.table("sections").select("id, page_title").eq("survey_id", survey_id).execute().data
        or []
    )
    section_map = {s["id"]: s for s in sections}
    section_ids = list(section_map.keys())
    if not section_ids:
        return []

    groups = (
        sb.table("feature_groups")
        .select("id, title, section_id")
        .in_("section_id", section_ids)
        .execute()
        .data
        or []
    )
    group_map = {g["id"]: g for g in groups}
    group_ids = list(group_map.keys())
    if not group_ids:
        return []

    features = [
        f
        for f in (
            sb.table("features")
            .select("id, feature_num, title, group_id, question_type")
            .in_("group_id", group_ids)
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
        if feature_question_type(f) == QUESTION_TYPE_YES_NO
    ]
    if not features:
        return []

    responses = (
        sb.table("responses").select("id").eq("survey_id", survey_id).execute().data or []
    )
    response_ids = [r["id"] for r in responses]
    answers = []
    if response_ids:
        answers = (
            sb.table("response_answers")
            .select("feature_id, rating")
            .in_("response_id", response_ids)
            .execute()
            .data
            or []
        )

    votes_by_feature = {}
    for a in answers:
        votes_by_feature.setdefault(a["feature_id"], []).append(a["rating"])

    items = []
    for f in features:
        g = group_map.get(f["group_id"], {})
        sec = section_map.get(g.get("section_id"), {})
        ratings = votes_by_feature.get(f["id"], [])
        yes_count = sum(1 for r in ratings if r == "yes")
        no_count = sum(1 for r in ratings if r == "no")
        total = yes_count + no_count
        items.append(
            {
                "feature_num": f["feature_num"],
                "title": f["title"],
                "group_title": g.get("title"),
                "page_title": sec.get("page_title"),
                "yes_count": yes_count,
                "no_count": no_count,
                "total_votes": total,
                "yes_pct": round(100 * yes_count / total, 1) if total else 0,
            }
        )
    items.sort(key=lambda x: (-x["yes_pct"], -x["yes_count"], x["feature_num"]))
    return items


def update_survey_settings(survey_id, data):
    sb = get_supabase()
    sb.table("surveys").update(data).eq("id", survey_id).execute()


def list_feature_groups(survey_id):
    sb = get_supabase()
    sections = (
        sb.table("sections")
        .select("id, page_order, page_title")
        .eq("survey_id", survey_id)
        .order("page_order")
        .execute()
        .data
        or []
    )
    section_ids = [s["id"] for s in sections]
    if not section_ids:
        return []
    groups = (
        sb.table("feature_groups")
        .select("id, title, section_id, sort_order")
        .in_("section_id", section_ids)
        .order("sort_order")
        .execute()
        .data
        or []
    )
    sec_title = {s["id"]: s["page_title"] for s in sections}
    return [
        {"id": g["id"], "title": g["title"], "page_title": sec_title.get(g["section_id"])}
        for g in groups
    ]


def list_all_features(survey_id):
    sb = get_supabase()
    sections = (
        sb.table("sections").select("id, page_title").eq("survey_id", survey_id).execute().data
        or []
    )
    section_ids = [s["id"] for s in sections]
    sec_title = {s["id"]: s["page_title"] for s in sections}
    if not section_ids:
        return []
    groups = (
        sb.table("feature_groups")
        .select("id, title, section_id")
        .in_("section_id", section_ids)
        .execute()
        .data
        or []
    )
    group_ids = [g["id"] for g in groups]
    group_meta = {g["id"]: g for g in groups}
    if not group_ids:
        return []
    features = (
        sb.table("features")
        .select("*")
        .in_("group_id", group_ids)
        .order("feature_num")
        .execute()
        .data
        or []
    )
    for f in features:
        g = group_meta.get(f["group_id"], {})
        f["group_title"] = g.get("title")
        f["page_title"] = sec_title.get(g.get("section_id"))
    return features


def add_feature(
    group_id, title, description, long_description, question_type=QUESTION_TYPE_RATING
):
    sb = get_supabase()
    existing = (
        sb.table("features")
        .select("feature_num")
        .eq("group_id", group_id)
        .order("feature_num", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    max_num = existing[0]["feature_num"] if existing else 0
    qtype = question_type if question_type in (QUESTION_TYPE_RATING, QUESTION_TYPE_YES_NO) else QUESTION_TYPE_RATING
    sb.table("features").insert(
        {
            "group_id": group_id,
            "feature_num": max_num + 1,
            "title": title,
            "description": description,
            "long_description": long_description,
            "sort_order": 999,
            "is_active": True,
            "question_type": qtype,
        }
    ).execute()


def update_feature(feature_id, data):
    get_supabase().table("features").update(data).eq("id", feature_id).execute()


def delete_feature(feature_id):
    get_supabase().table("features").delete().eq("id", feature_id).execute()


def list_responses(survey_id):
    sb = get_supabase()
    responses = (
        sb.table("responses")
        .select("*")
        .eq("survey_id", survey_id)
        .order("submitted_at", desc=True)
        .execute()
        .data
        or []
    )
    if not responses:
        return []
    ids = [r["id"] for r in responses]
    counts_raw = (
        sb.table("response_answers")
        .select("response_id")
        .in_("response_id", ids)
        .execute()
        .data
        or []
    )
    counts = {}
    for row in counts_raw:
        rid = row["response_id"]
        counts[rid] = counts.get(rid, 0) + 1
    for r in responses:
        r["answer_count"] = counts.get(r["id"], 0)
    return responses


def get_response(response_id):
    sb = get_supabase()
    rows = (
        sb.table("responses").select("*").eq("id", response_id).limit(1).execute().data or []
    )
    return rows[0] if rows else None


def delete_response(response_id):
    get_supabase().table("responses").delete().eq("id", response_id).execute()


def get_response_answers(response_id):
    sb = get_supabase()
    answers = (
        sb.table("response_answers")
        .select("feature_id, rating")
        .eq("response_id", response_id)
        .execute()
        .data
        or []
    )
    if not answers:
        return []
    feature_ids = [a["feature_id"] for a in answers]
    features = (
        sb.table("features")
        .select("id, feature_num, title, question_type")
        .in_("id", feature_ids)
        .execute()
        .data
        or []
    )
    fmap = {f["id"]: f for f in features}
    result = []
    for a in answers:
        f = fmap.get(a["feature_id"], {})
        rating = a["rating"]
        result.append(
            {
                "feature_num": f.get("feature_num"),
                "title": f.get("title"),
                "rating": rating,
                "rating_label": answer_label(rating),
                "question_type": feature_question_type(f),
            }
        )
    result.sort(key=lambda x: x.get("feature_num") or 0)
    return result


def export_survey_data(survey_id):
    features = list_all_features(survey_id)
    features.sort(key=lambda x: x["feature_num"])
    responses = (
        get_supabase()
        .table("responses")
        .select("*")
        .eq("survey_id", survey_id)
        .order("submitted_at", desc=True)
        .execute()
        .data
        or []
    )
    return features, responses


def get_answers_for_responses(response_ids):
    if not response_ids:
        return {}
    rows = (
        get_supabase()
        .table("response_answers")
        .select("response_id, feature_id, rating")
        .in_("response_id", response_ids)
        .execute()
        .data
        or []
    )
    by_response = {}
    for row in rows:
        by_response.setdefault(row["response_id"], {})[row["feature_id"]] = row["rating"]
    return by_response
