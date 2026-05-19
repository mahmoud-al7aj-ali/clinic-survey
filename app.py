import csv
import io
import os
from functools import wraps

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
    count_active_features,
    feature_rating_rankings,
    email_used_by_other,
    find_existing_response,
    get_active_survey,
    get_db,
    init_db,
    survey_structure,
    utc_now,
)
from seed import seed

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
    else:
        with get_db() as conn:
            if conn.execute("SELECT COUNT(*) FROM surveys").fetchone()[0] == 0:
                seed()
    _db_ready = True


# ─── Public survey ───────────────────────────────────────────────

@app.route("/")
def survey():
    with get_db() as conn:
        survey_row = get_active_survey(conn)
        if not survey_row:
            return "لا يوجد استبيان نشط.", 404
        structure = survey_structure(conn, survey_row["id"])
        total = count_active_features(conn, survey_row["id"])
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

    with get_db() as conn:
        survey_row = get_active_survey(conn)
        if not survey_row:
            return jsonify({"ok": False, "error": "لا يوجد استبيان نشط"}), 404

        features = conn.execute(
            """
            SELECT f.id, f.feature_num FROM features f
            JOIN feature_groups g ON g.id = f.group_id
            JOIN sections s ON s.id = g.section_id
            WHERE s.survey_id = ? AND f.is_active = 1
            """,
            (survey_row["id"],),
        ).fetchall()
        by_num = {str(f["feature_num"]): f["id"] for f in features}
        expected = set(by_num.keys())
        provided = set(str(k) for k in answers.keys())

        if provided != expected:
            missing = expected - provided
            return jsonify(
                {
                    "ok": False,
                    "error": f"يرجى تقييم جميع الميزات ({len(provided)}/{len(expected)})",
                    "missing": list(missing),
                }
            ), 400

        for k, v in answers.items():
            if v not in RATING_LABELS:
                return jsonify({"ok": False, "error": "تقييم غير صالح"}), 400

        existing_id = find_existing_response(
            conn, survey_row["id"], phone, email or None
        )
        if existing_id == "conflict":
            return jsonify(
                {
                    "ok": False,
                    "error": "رقم الهاتف والبريد مرتبطان بإجابتين مختلفتين. استخدم نفس بيانات الإرسال الأول.",
                }
            ), 409

        now = utc_now()
        if existing_id:
            if email and email_used_by_other(
                conn, survey_row["id"], email, existing_id
            ):
                return jsonify(
                    {
                        "ok": False,
                        "error": "هذا البريد الإلكتروني مستخدم في إجابة أخرى.",
                    }
                ), 409
            conn.execute(
                """
                UPDATE responses
                SET doctor_name=?, clinic_name=?, phone=?, email=?, notes=?,
                    wants_updates=?, submitted_at=?
                WHERE id=? AND survey_id=?
                """,
                (
                    doctor,
                    clinic,
                    phone,
                    email or None,
                    notes,
                    wants_updates,
                    now,
                    existing_id,
                    survey_row["id"],
                ),
            )
            conn.execute(
                "DELETE FROM response_answers WHERE response_id = ?",
                (existing_id,),
            )
            response_id = existing_id
            success_message = "تم تحديث إجاباتك بنجاح"
            updated = True
        else:
            cur = conn.execute(
                """
                INSERT INTO responses (
                    survey_id, doctor_name, clinic_name, phone, email, notes,
                    wants_updates, submitted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    survey_row["id"],
                    doctor,
                    clinic,
                    phone,
                    email or None,
                    notes,
                    wants_updates,
                    now,
                ),
            )
            response_id = cur.lastrowid
            success_message = "شكراً — تم حفظ إجاباتك بنجاح"
            updated = False

        for num, rating in answers.items():
            conn.execute(
                """
                INSERT INTO response_answers (response_id, feature_id, rating)
                VALUES (?, ?, ?)
                """,
                (response_id, by_num[str(num)], rating),
            )

    return jsonify(
        {"ok": True, "message": success_message, "updated": updated}
    )


# ─── Admin auth ──────────────────────────────────────────────────

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_id"):
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        with get_db() as conn:
            user = conn.execute(
                "SELECT * FROM admin_users WHERE username = ?", (username,)
            ).fetchone()
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
    with get_db() as conn:
        survey_row = get_active_survey(conn)
        if not survey_row:
            return render_template("admin/dashboard.html", survey=None)

        total_responses = conn.execute(
            "SELECT COUNT(*) FROM responses WHERE survey_id = ?",
            (survey_row["id"],),
        ).fetchone()[0]
        total_features = count_active_features(conn, survey_row["id"])
        recent = conn.execute(
            """
            SELECT id, doctor_name, clinic_name, submitted_at
            FROM responses WHERE survey_id = ?
            ORDER BY submitted_at DESC LIMIT 10
            """,
            (survey_row["id"],),
        ).fetchall()
        rating_rows = conn.execute(
            """
            SELECT ra.rating, COUNT(*) as cnt
            FROM response_answers ra
            JOIN responses r ON r.id = ra.response_id
            WHERE r.survey_id = ?
            GROUP BY ra.rating
            """,
            (survey_row["id"],),
        ).fetchall()
        rating_counts = {row["rating"]: row["cnt"] for row in rating_rows}
        sort_by = request.args.get("sort", "score")
        if sort_by not in ("score", "very_important", "num"):
            sort_by = "score"
        feature_rankings = feature_rating_rankings(conn, survey_row["id"], sort_by)
        rated_features_count = sum(1 for f in feature_rankings if f["total_votes"])

    return render_template(
        "admin/dashboard.html",
        survey=survey_row,
        total_responses=total_responses,
        total_features=total_features,
        rated_features_count=rated_features_count,
        recent=recent,
        rating_counts=rating_counts,
        rating_labels=RATING_LABELS,
        feature_rankings=feature_rankings,
        sort_by=sort_by,
    )


@app.route("/admin/survey", methods=["GET", "POST"])
@login_required
def admin_survey_settings():
    with get_db() as conn:
        survey_row = get_active_survey(conn)
        if not survey_row:
            flash("لا يوجد استبيان", "error")
            return redirect(url_for("admin_dashboard"))

        if request.method == "POST":
            conn.execute(
                """
                UPDATE surveys SET
                    title=?, brand_name=?, tag=?, intro_text=?,
                    promo_enabled=?, promo_badge=?, promo_text=?
                WHERE id=?
                """,
                (
                    request.form.get("title", "").strip(),
                    request.form.get("brand_name", "").strip(),
                    request.form.get("tag", "").strip(),
                    request.form.get("intro_text", "").strip(),
                    1 if request.form.get("promo_enabled") else 0,
                    request.form.get("promo_badge", "").strip(),
                    request.form.get("promo_text", "").strip(),
                    survey_row["id"],
                ),
            )
            flash("تم حفظ إعدادات الاستبيان", "ok")
            return redirect(url_for("admin_survey_settings"))

    return render_template("admin/survey_settings.html", survey=survey_row)


@app.route("/admin/features", methods=["GET", "POST"])
@login_required
def admin_features():
    with get_db() as conn:
        survey_row = get_active_survey(conn)
        if not survey_row:
            flash("لا يوجد استبيان", "error")
            return redirect(url_for("admin_dashboard"))

        if request.method == "POST":
            action = request.form.get("action")
            if action == "add":
                group_id = request.form.get("group_id")
                if group_id:
                    max_num = conn.execute(
                        "SELECT COALESCE(MAX(feature_num), 0) FROM features WHERE group_id = ?",
                        (group_id,),
                    ).fetchone()[0]
                    short = request.form.get("description", "").strip()
                    long_d = request.form.get("long_description", "").strip() or short
                    conn.execute(
                        """
                        INSERT INTO features (group_id, feature_num, title, description, long_description, sort_order, is_active)
                        VALUES (?, ?, ?, ?, ?, 999, 1)
                        """,
                        (
                            group_id,
                            max_num + 1,
                            request.form.get("title", "ميزة جديدة").strip(),
                            short,
                            long_d,
                        ),
                    )
                    flash("تمت إضافة الميزة", "ok")
            elif action == "save":
                fid = request.form.get("feature_id")
                short = request.form.get("description", "").strip()
                long_d = request.form.get("long_description", "").strip()
                conn.execute(
                    """
                    UPDATE features SET title=?, description=?, long_description=?, feature_num=?, is_active=?
                    WHERE id=?
                    """,
                    (
                        request.form.get("title", "").strip(),
                        short,
                        long_d or short,
                        int(request.form.get("feature_num") or 0),
                        1 if request.form.get("is_active") else 0,
                        fid,
                    ),
                )
                flash("تم الحفظ", "ok")
            elif action == "delete":
                fid = request.form.get("feature_id")
                conn.execute("DELETE FROM features WHERE id = ?", (fid,))
                flash("تم الحذف", "ok")
            return redirect(url_for("admin_features"))

        structure = survey_structure(conn, survey_row["id"])
        all_groups = conn.execute(
            """
            SELECT g.id, g.title, s.page_title
            FROM feature_groups g
            JOIN sections s ON s.id = g.section_id
            WHERE s.survey_id = ?
            ORDER BY s.page_order, g.sort_order
            """,
            (survey_row["id"],),
        ).fetchall()
        all_features = conn.execute(
            """
            SELECT f.*, g.title as group_title, s.page_title
            FROM features f
            JOIN feature_groups g ON g.id = f.group_id
            JOIN sections s ON s.id = g.section_id
            WHERE s.survey_id = ?
            ORDER BY f.feature_num
            """,
            (survey_row["id"],),
        ).fetchall()

    return render_template(
        "admin/features.html",
        survey=survey_row,
        structure=structure,
        all_groups=all_groups,
        all_features=all_features,
    )


@app.route("/admin/responses")
@login_required
def admin_responses():
    with get_db() as conn:
        survey_row = get_active_survey(conn)
        rows = []
        if survey_row:
            rows = conn.execute(
                """
                SELECT r.*,
                  (SELECT COUNT(*) FROM response_answers WHERE response_id = r.id) as answer_count
                FROM responses r
                WHERE r.survey_id = ?
                ORDER BY r.submitted_at DESC
                """,
                (survey_row["id"],),
            ).fetchall()
    return render_template("admin/responses.html", responses=rows, survey=survey_row)


@app.route("/admin/responses/<int:response_id>/delete", methods=["POST"])
@login_required
def admin_response_delete(response_id):
    with get_db() as conn:
        resp = conn.execute(
            "SELECT id, doctor_name FROM responses WHERE id = ?", (response_id,)
        ).fetchone()
        if not resp:
            flash("الإجابة غير موجودة", "error")
            return redirect(url_for("admin_responses"))
        conn.execute("DELETE FROM responses WHERE id = ?", (response_id,))
    flash(f"تم حذف إجابة الطبيب «{resp['doctor_name']}»", "ok")
    return redirect(url_for("admin_responses"))


@app.route("/admin/responses/<int:response_id>")
@login_required
def admin_response_detail(response_id):
    with get_db() as conn:
        resp = conn.execute(
            "SELECT * FROM responses WHERE id = ?", (response_id,)
        ).fetchone()
        if not resp:
            return "غير موجود", 404
        answers = conn.execute(
            """
            SELECT f.feature_num, f.title, ra.rating
            FROM response_answers ra
            JOIN features f ON f.id = ra.feature_id
            WHERE ra.response_id = ?
            ORDER BY f.feature_num
            """,
            (response_id,),
        ).fetchall()
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
    with get_db() as conn:
        survey_row = get_active_survey(conn)
        if not survey_row:
            return "لا يوجد استبيان", 404

        features = conn.execute(
            """
            SELECT f.id, f.feature_num, f.title FROM features f
            JOIN feature_groups g ON g.id = f.group_id
            JOIN sections s ON s.id = g.section_id
            WHERE s.survey_id = ?
            ORDER BY f.feature_num
            """,
            (survey_row["id"],),
        ).fetchall()

        responses = conn.execute(
            "SELECT * FROM responses WHERE survey_id = ? ORDER BY submitted_at DESC",
            (survey_row["id"],),
        ).fetchall()

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
        ] + [
            f"{f['feature_num']}. {f['title']}" for f in features
        ]
        writer.writerow(header)

        for r in responses:
            ans_rows = conn.execute(
                "SELECT feature_id, rating FROM response_answers WHERE response_id = ?",
                (r["id"],),
            ).fetchall()
            ans_map = {a["feature_id"]: a["rating"] for a in ans_rows}
            row = [
                r["id"],
                r["doctor_name"],
                r["clinic_name"],
                r["phone"] or "",
                r["email"] or "",
                r["notes"] or "",
                "yes" if r["wants_updates"] else "no",
                r["submitted_at"],
            ]
            for f in features:
                rating = ans_map.get(f["id"], "")
                row.append(RATING_LABELS.get(rating, rating))
            writer.writerow(row)

        output = buf.getvalue()
        return app.response_class(
            output,
            mimetype="text/csv; charset=utf-8-sig",
            headers={
                "Content-Disposition": "attachment; filename=survey_responses.csv"
            },
        )


if __name__ == "__main__":
    init_db()
    if not os.path.exists(os.path.join(os.path.dirname(__file__), "survey.db")):
        seed()
    port = int(os.environ.get("PORT", 8765))
    app.run(host="0.0.0.0", port=port, debug=True)
