import csv
import io
import os
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from database import (
    RATING_LABELS,
    add_feature,
    count_active_features,
    count_responses,
    delete_feature,
    delete_response,
    export_survey_data,
    feature_rating_rankings,
    get_active_survey,
    get_admin_user,
    get_answers_for_responses,
    get_response,
    get_response_answers,
    get_survey_features,
    init_db,
    list_all_features,
    list_feature_groups,
    list_responses,
    rating_counts_for_survey,
    recent_responses,
    save_survey_response,
    survey_count,
    survey_structure,
    update_feature,
    update_survey_settings,
    utc_now,
)
from seed import seed

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production-clinic-survey")


def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login", next=request.path))
        return f(*args, **kwargs)

    return wrapped


_db_ready = False


@app.before_request
def ensure_db():
    global _db_ready
    if _db_ready:
        return
    init_db()
    if os.environ.get("SEED_FORCE") == "1":
        seed(force=True)
    elif survey_count() == 0:
        seed()
    _db_ready = True


# ─── Public survey ───────────────────────────────────────────────

@app.route("/")
def survey():
    survey_row = get_active_survey()
    if not survey_row:
        return "لا يوجد استبيان نشط.", 404
    structure = survey_structure(survey_row["id"])
    total = count_active_features(survey_row["id"])
    return render_template(
        "survey.html",
        survey=survey_row,
        structure=structure,
        total=total,
        rating_labels=RATING_LABELS,
    )


@app.route("/api/submit", methods=["POST"])
def api_submit():
    data = request.get_json(silent=True) or {}
    doctor = (data.get("doctor_name") or "").strip()
    clinic = (data.get("clinic_name") or "").strip()
    phone = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip()
    notes = (data.get("notes") or "").strip()
    wants_updates = 1 if data.get("wants_updates") else 0
    answers = data.get("answers") or {}

    if not doctor or not clinic or not phone:
        return jsonify({"ok": False, "error": "اسم الطبيب واسم العيادة ورقم الهاتف مطلوبان"}), 400

    if email and "@" not in email:
        return jsonify({"ok": False, "error": "البريد الإلكتروني غير صالح"}), 400

    survey_row = get_active_survey()
    if not survey_row:
        return jsonify({"ok": False, "error": "لا يوجد استبيان نشط"}), 404

    features = get_survey_features(survey_row["id"])
    by_num = {str(f["feature_num"]): f["id"] for f in features}
    expected = set(by_num.keys())
    provided = set(str(k) for k in answers.keys())

    if provided != expected:
        return jsonify(
            {
                "ok": False,
                "error": f"يرجى تقييم جميع الميزات ({len(provided)}/{len(expected)})",
                "missing": list(expected - provided),
            }
        ), 400

    for v in answers.values():
        if v not in RATING_LABELS:
            return jsonify({"ok": False, "error": "تقييم غير صالح"}), 400

    _, err, updated = save_survey_response(
        survey_row["id"],
        doctor,
        clinic,
        phone,
        email,
        notes,
        wants_updates,
        answers,
        by_num,
    )
    if err == "conflict":
        return jsonify(
            {
                "ok": False,
                "error": "رقم الهاتف والبريد مرتبطان بإجابتين مختلفتين. استخدم نفس بيانات الإرسال الأول.",
            }
        ), 409
    if err == "email_taken":
        return jsonify(
            {"ok": False, "error": "هذا البريد الإلكتروني مستخدم في إجابة أخرى."}
        ), 409

    message = "تم تحديث إجاباتك بنجاح" if updated else "شكراً — تم حفظ إجاباتك بنجاح"
    return jsonify({"ok": True, "message": message, "updated": updated})


# ─── Admin auth ──────────────────────────────────────────────────

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_id"):
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = get_admin_user(username)
        if user and check_password_hash(user["password_hash"], password):
            session["admin_id"] = user["id"]
            session["admin_username"] = user["username"]
            return redirect(request.args.get("next") or url_for("admin_dashboard"))
        flash("اسم المستخدم أو كلمة المرور غير صحيحة", "error")

    return render_template("admin/login.html")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


# ─── Admin dashboard ─────────────────────────────────────────────

@app.route("/admin")
@login_required
def admin_dashboard():
    survey_row = get_active_survey()
    if not survey_row:
        return render_template("admin/dashboard.html", survey=None)

    sid = survey_row["id"]
    total_responses = count_responses(sid)
    total_features = count_active_features(sid)
    recent = recent_responses(sid)
    rating_counts = rating_counts_for_survey(sid)
    sort_by = request.args.get("sort", "score")
    if sort_by not in ("score", "very_important", "num"):
        sort_by = "score"
    feature_rankings_list = feature_rating_rankings(sid, sort_by)
    rated_features_count = sum(1 for f in feature_rankings_list if f["total_votes"])

    return render_template(
        "admin/dashboard.html",
        survey=survey_row,
        total_responses=total_responses,
        total_features=total_features,
        rated_features_count=rated_features_count,
        recent=recent,
        rating_counts=rating_counts,
        rating_labels=RATING_LABELS,
        feature_rankings=feature_rankings_list,
        sort_by=sort_by,
    )


@app.route("/admin/survey", methods=["GET", "POST"])
@login_required
def admin_survey_settings():
    survey_row = get_active_survey()
    if not survey_row:
        flash("لا يوجد استبيان", "error")
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        update_survey_settings(
            survey_row["id"],
            {
                "title": request.form.get("title", "").strip(),
                "brand_name": request.form.get("brand_name", "").strip(),
                "tag": request.form.get("tag", "").strip(),
                "intro_text": request.form.get("intro_text", "").strip(),
                "promo_enabled": bool(request.form.get("promo_enabled")),
                "promo_badge": request.form.get("promo_badge", "").strip(),
                "promo_text": request.form.get("promo_text", "").strip(),
            },
        )
        flash("تم حفظ إعدادات الاستبيان", "ok")
        return redirect(url_for("admin_survey_settings"))

    return render_template("admin/survey_settings.html", survey=survey_row)


@app.route("/admin/features", methods=["GET", "POST"])
@login_required
def admin_features():
    survey_row = get_active_survey()
    if not survey_row:
        flash("لا يوجد استبيان", "error")
        return redirect(url_for("admin_dashboard"))

    sid = survey_row["id"]
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            group_id = request.form.get("group_id")
            if group_id:
                short = request.form.get("description", "").strip()
                long_d = request.form.get("long_description", "").strip() or short
                add_feature(
                    int(group_id),
                    request.form.get("title", "ميزة جديدة").strip(),
                    short,
                    long_d,
                )
                flash("تمت إضافة الميزة", "ok")
        elif action == "save":
            fid = request.form.get("feature_id")
            short = request.form.get("description", "").strip()
            long_d = request.form.get("long_description", "").strip()
            update_feature(
                int(fid),
                {
                    "title": request.form.get("title", "").strip(),
                    "description": short,
                    "long_description": long_d or short,
                    "feature_num": int(request.form.get("feature_num") or 0),
                    "is_active": bool(request.form.get("is_active")),
                },
            )
            flash("تم الحفظ", "ok")
        elif action == "delete":
            delete_feature(int(request.form.get("feature_id")))
            flash("تم الحذف", "ok")
        return redirect(url_for("admin_features"))

    return render_template(
        "admin/features.html",
        survey=survey_row,
        structure=survey_structure(sid),
        all_groups=list_feature_groups(sid),
        all_features=list_all_features(sid),
    )


@app.route("/admin/responses")
@login_required
def admin_responses():
    survey_row = get_active_survey()
    rows = list_responses(survey_row["id"]) if survey_row else []
    return render_template("admin/responses.html", responses=rows, survey=survey_row)


@app.route("/admin/responses/<int:response_id>/delete", methods=["POST"])
@login_required
def admin_response_delete(response_id):
    resp = get_response(response_id)
    if not resp:
        flash("الإجابة غير موجودة", "error")
        return redirect(url_for("admin_responses"))
    delete_response(response_id)
    flash(f"تم حذف إجابة الطبيب «{resp['doctor_name']}»", "ok")
    return redirect(url_for("admin_responses"))


@app.route("/admin/responses/<int:response_id>")
@login_required
def admin_response_detail(response_id):
    resp = get_response(response_id)
    if not resp:
        return "غير موجود", 404
    answers = get_response_answers(response_id)
    grouped = {k: [] for k in RATING_LABELS}
    for a in answers:
        grouped[a["rating"]].append(a)
    return render_template(
        "admin/response_detail.html",
        response=resp,
        grouped=grouped,
        rating_labels=RATING_LABELS,
    )


@app.route("/admin/export.csv")
@login_required
def admin_export_csv():
    survey_row = get_active_survey()
    if not survey_row:
        return "لا يوجد استبيان", 404

    features, responses = export_survey_data(survey_row["id"])
    ans_by_response = get_answers_for_responses([r["id"] for r in responses])

    buf = io.StringIO()
    writer = csv.writer(buf)
    header = [
        "id",
        "doctor",
        "clinic",
        "phone",
        "email",
        "notes",
        "wants_updates",
        "submitted_at",
    ] + [f"{f['feature_num']}. {f['title']}" for f in features]
    writer.writerow(header)

    for r in responses:
        ans_map = ans_by_response.get(r["id"], {})
        row = [
            r["id"],
            r["doctor_name"],
            r["clinic_name"],
            r.get("phone") or "",
            r.get("email") or "",
            r.get("notes") or "",
            "yes" if r.get("wants_updates") else "no",
            r.get("submitted_at") or "",
        ]
        for f in features:
            rating = ans_map.get(f["id"], "")
            row.append(RATING_LABELS.get(rating, rating))
        writer.writerow(row)

    return app.response_class(
        buf.getvalue(),
        mimetype="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": "attachment; filename=survey_responses.csv"},
    )


if __name__ == "__main__":
    init_db()
    if survey_count() == 0:
        seed()
    port = int(os.environ.get("PORT", 8765))
    app.run(host="0.0.0.0", port=port, debug=True)
