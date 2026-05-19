(function () {
  const RATING_LABELS = {
    very_important: "مهمة جداً",
    important: "مهمة",
    nice_to_have: "مفيدة",
    not_needed: "غير ضرورية",
  };
  const YES_NO_LABELS = { yes: "نعم", no: "لا" };

  let supabase;
  let surveyRow;
  let featuresByNum = {};
  let featureIdByNum = {};

  function esc(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function normalizePhone(phone) {
    return (phone || "").replace(/\D/g, "");
  }

  function showError(msg) {
    document.getElementById("app-loading").classList.add("is-hidden");
    document.getElementById("app-root").classList.add("is-hidden");
    const el = document.getElementById("app-error");
    el.textContent = msg;
    el.classList.remove("is-hidden");
  }

  async function loadSurveyStructure(surveyId) {
    const { data: sections, error: secErr } = await supabase
      .from("sections")
      .select("*")
      .eq("survey_id", surveyId)
      .order("page_order");
    if (secErr) throw secErr;

    const structure = [];
    let total = 0;

    for (const section of sections || []) {
      const { data: groups } = await supabase
        .from("feature_groups")
        .select("*")
        .eq("section_id", section.id)
        .order("sort_order")
        .order("id");

      const groupList = [];
      for (const group of groups || []) {
        const { data: features } = await supabase
          .from("features")
          .select("*")
          .eq("group_id", group.id)
          .eq("is_active", true)
          .order("sort_order")
          .order("feature_num");

        if (features && features.length) {
          groupList.push({ group, features });
          total += features.length;
          features.forEach((f) => {
            featuresByNum[String(f.feature_num)] = f;
            featureIdByNum[String(f.feature_num)] = f.id;
          });
        }
      }
      if (groupList.length) structure.push({ section, groups: groupList });
    }
    return { structure, total };
  }

  function renderRatingButtons(f) {
    const opts = [
      ["very_important", "g"],
      ["important", "y"],
      ["nice_to_have", "o"],
      ["not_needed", "r"],
    ];
    return opts
      .map(
        ([val, cls]) =>
          `<button type="button" class="rb ${cls}" data-value="${val}" aria-pressed="false">
        <span class="rb-circle"></span><span class="rb-lbl">${RATING_LABELS[val]}</span></button>`
      )
      .join("");
  }

  function renderFeatureRow(f, odd) {
    const qtype = f.question_type || "rating";
    const rateCell =
      qtype === "yes_no"
        ? `<div class="rb-wrap rb-wrap-yn" role="radiogroup" aria-label="${esc(f.title)}">
        <button type="button" class="rb yn-yes" data-value="yes" aria-pressed="false"><span class="rb-circle"></span><span class="rb-lbl">${YES_NO_LABELS.yes}</span></button>
        <button type="button" class="rb yn-no" data-value="no" aria-pressed="false"><span class="rb-circle"></span><span class="rb-lbl">${YES_NO_LABELS.no}</span></button>
      </div>`
        : `<div class="rb-wrap" role="radiogroup" aria-label="${esc(f.title)}">${renderRatingButtons(f)}</div>`;

    const detailsBtn =
      f.long_description || f.description
        ? `<button type="button" class="btn-details" data-feature-id="${f.id}" aria-label="اضغط لمزيد من التفاصيل">اضغط لمزيد من التفاصيل</button>`
        : "";

    return `<tr class="${odd ? "odd" : "even"}" data-feature-num="${f.feature_num}" data-question-type="${qtype}">
      <td class="c-rate">${rateCell}</td>
      <td class="c-desc">
        <div class="fn-row"><span class="fn">${esc(f.title)}</span>${detailsBtn}</div>
        <div class="fi">${esc(f.description || "")}</div>
        <template id="long-desc-${f.id}">${esc(f.long_description || f.description || "")}</template>
      </td>
      <td class="c-num">${f.feature_num}</td>
    </tr>`;
  }

  function renderSurvey(survey, structure, total) {
    document.title = survey.title;

    let pagesHtml = "";
    structure.forEach((page, pageIdx) => {
      let groupsHtml = "";
      page.groups.forEach((block) => {
        let rows = "";
        block.features.forEach((f, i) => {
          rows += renderFeatureRow(f, i % 2 === 0);
        });
        groupsHtml += `
        <div class="sh">
          <div class="sh-inner">
            <span class="sh-badge">${block.features.length} ميزات</span>
            <div class="sh-text-cell"><h3>${esc(block.group.title)}</h3><p>${esc(block.group.subtitle || "")}</p></div>
            <span class="sh-icon">${esc(block.group.icon)}</span>
          </div>
        </div>
        <table class="ft">
          <thead><tr class="fth">
            <td class="h-rate">الإجابة</td>
            <td class="h-desc">الميزة والوصف</td>
            <td class="h-num">#</td>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>`;
      });

      pagesHtml += `
      <div class="page">
        <div class="stripe"></div>
        <header class="ph">
          <div class="ph-inner">
            <div class="ph-text">
              <div class="ph-lbl">${esc(page.section.page_label)}</div>
              <h2 class="ph-ttl">${esc(page.section.page_title)}</h2>
            </div>
            <span class="ph-num">${esc(page.section.page_num)}</span>
          </div>
        </header>
        <div class="pb">${groupsHtml}</div>
        <div class="pf">
          <table style="width:100%"><tr>
            <td class="pf-brand">${esc(survey.brand_name)}</td>
            <td class="pf-num">${pageIdx + 1} / ${structure.length}</td>
          </tr></table>
        </div>
      </div>`;
    });

    const promo =
      survey.promo_enabled && (survey.promo_badge || survey.promo_text)
        ? `<div class="cover-promo cover-promo--header">
        ${survey.promo_badge ? `<span class="cover-promo-badge">${esc(survey.promo_badge)}</span>` : ""}
        ${survey.promo_text ? `<p class="cover-promo-text">${survey.promo_text}</p>` : ""}
      </div>`
        : "";

    return `
    <div id="success-banner" class="success-banner"></div>
    <div class="cover">
      <div class="deco" style="width:460px;height:460px;background:#1A56A0;opacity:0.28;top:-160px;right:-150px;"></div>
      <div class="deco" style="width:280px;height:280px;background:#00C9A7;opacity:0.1;bottom:50px;left:-80px;"></div>
      <header class="cover-top">
        <div class="cover-top-inner">
          <span class="brand">${esc(survey.brand_name)}</span>
          <span class="tag">${esc(survey.tag || "")}</span>
        </div>
        ${promo}
      </header>
      <div class="cover-body">
        <div class="eyebrow">— استطلاع رأي الأطباء</div>
        <div class="cover-h1">ميزات<br><span class="acc">النظام</span></div>
        <div class="cover-sub">تقييم الميزات المقترحة لعيادتك</div>
        <div class="rule"></div>
        <div class="cover-intro-block">
          <div class="intro-box">${esc(survey.intro_text || "")}</div>
          <div class="cover-cta-wrap">
            <button type="button" class="cover-cta" id="btn-start">ابدأ الاستبيان ←</button>
          </div>
        </div>
        <div class="cover-stats-block">
          <div class="stats-wrap">
            <table class="stats-tbl"><tr>
              <td><span class="sn">${total}</span><span class="sl">ميزة مقترحة</span></td>
              <td><span class="sn">${structure.length}</span><span class="sl">محاور رئيسية</span></td>
              <td><span class="sn">5 د</span><span class="sl">وقت التعبئة</span></td>
            </tr></table>
          </div>
        </div>
      </div>
      <div class="cover-btm">
        <table><tr>
          <td class="note-r">اضغط على كل ميزة ثم أرسل إجاباتك في النهاية</td>
          <td class="note-l">© 2025</td>
        </tr></table>
      </div>
    </div>
    ${pagesHtml}
    <div class="closing">
      <div class="cl-icon">🙏</div>
      <div class="cl-title">شكراً لمشاركتك</div>
      <div class="cl-sub">عبّئ بياناتك وأرسل إجاباتك — يمكنك التعديل لاحقاً بنفس رقم الهاتف أو البريد</div>
      <div class="submit-panel" id="submit-panel">
        <h3>بيانات العيادة</h3>
        <input type="text" class="field" id="doctor-name" placeholder="اسم الطبيب *" autocomplete="name" required>
        <input type="text" class="field" id="clinic-name" placeholder="اسم العيادة *" autocomplete="organization" required>
        <input type="tel" class="field" id="phone" placeholder="رقم الهاتف *" autocomplete="tel" required>
        <input type="email" class="field" id="email" placeholder="البريد الإلكتروني (اختياري)" autocomplete="email">
        <textarea class="field field-notes" id="notes" placeholder="ملاحظات إضافية (اختياري)"></textarea>
        <label class="updates-opt-in" for="wants-updates">
          <input type="checkbox" id="wants-updates" name="wants_updates">
          <span>أرغب في استلام آخر التحديثات والأخبار عبر البريد الإلكتروني أو رقم الهاتف</span>
        </label>
        <button type="button" class="btn-submit btn-save" id="btn-save">إرسال الإجابات</button>
        <p class="submit-msg" id="submit-msg"></p>
      </div>
    </div>
    <div class="progress-dock is-hidden" id="progress-dock">
      <div class="progress-track"><div class="progress-fill" id="progress-fill"></div></div>
      <span class="progress-text" id="progress-text">0 / ${total}</span>
      <button type="button" class="btn-dock" id="btn-goto-submit" disabled>إرسال</button>
    </div>
    <div class="detail-modal is-hidden" id="detail-modal" role="dialog" aria-modal="true" aria-labelledby="detail-modal-title">
      <div class="detail-modal-backdrop" id="detail-modal-backdrop"></div>
      <div class="detail-modal-box">
        <button type="button" class="detail-modal-close" id="detail-modal-close" aria-label="إغلاق">×</button>
        <h3 class="detail-modal-title" id="detail-modal-title"></h3>
        <div class="detail-modal-body" id="detail-modal-body"></div>
      </div>
    </div>`;
  }

  function isValidAnswer(feature, value) {
    const qtype = feature.question_type || "rating";
    if (qtype === "yes_no") return value === "yes" || value === "no";
    return Object.keys(RATING_LABELS).includes(value);
  }

  async function findExistingResponse(surveyId, phone, email) {
    const { data: rows } = await supabase
      .from("responses")
      .select("id, phone, email")
      .eq("survey_id", surveyId);
    const normPhone = normalizePhone(phone);
    const normEmail = (email || "").trim().toLowerCase();
    let byPhone = null;
    let byEmail = null;
    (rows || []).forEach((row) => {
      if (normPhone && normalizePhone(row.phone) === normPhone) byPhone = row.id;
      const re = (row.email || "").trim().toLowerCase();
      if (normEmail && re && re === normEmail) byEmail = row.id;
    });
    if (byPhone && byEmail && byPhone !== byEmail) return "conflict";
    return byPhone || byEmail;
  }

  async function emailUsedByOther(surveyId, email, excludeId) {
    const normEmail = (email || "").trim().toLowerCase();
    if (!normEmail) return false;
    const { data: rows } = await supabase
      .from("responses")
      .select("id, email")
      .eq("survey_id", surveyId)
      .neq("id", excludeId);
    return (rows || []).some((r) => (r.email || "").trim().toLowerCase() === normEmail);
  }

  async function submitAnswers(payload) {
    const { doctor_name, clinic_name, phone, email, notes, wants_updates, answers } = payload;
    const surveyId = surveyRow.id;

    const expected = new Set(Object.keys(featureIdByNum));
    const provided = new Set(Object.keys(answers));
    if (expected.size !== provided.size || [...expected].some((k) => !provided.has(k))) {
      throw new Error(
        `يرجى الإجابة على جميع الأسئلة (${provided.size}/${expected.size})`
      );
    }

    for (const [num, val] of Object.entries(answers)) {
      const feature = featuresByNum[num];
      if (!feature || !isValidAnswer(feature, val)) throw new Error("إجابة غير صالحة");
    }

    const existingId = await findExistingResponse(surveyId, phone, email);
    if (existingId === "conflict") {
      throw new Error(
        "رقم الهاتف والبريد مرتبطان بإجابتين مختلفتين. استخدم نفس بيانات الإرسال الأول."
      );
    }

    const now = new Date().toISOString();
    const row = {
      doctor_name,
      clinic_name,
      phone,
      email: email || null,
      notes,
      wants_updates: !!wants_updates,
      submitted_at: now,
    };

    let responseId;
    let updated = false;

    if (existingId) {
      if (email && (await emailUsedByOther(surveyId, email, existingId))) {
        throw new Error("هذا البريد الإلكتروني مستخدم في إجابة أخرى.");
      }
      const { error } = await supabase
        .from("responses")
        .update(row)
        .eq("id", existingId)
        .eq("survey_id", surveyId);
      if (error) throw error;
      await supabase.from("response_answers").delete().eq("response_id", existingId);
      responseId = existingId;
      updated = true;
    } else {
      const { data, error } = await supabase
        .from("responses")
        .insert({ ...row, survey_id: surveyId })
        .select("id")
        .single();
      if (error) throw error;
      responseId = data.id;
    }

    const answerRows = Object.entries(answers).map(([num, rating]) => ({
      response_id: responseId,
      feature_id: featureIdByNum[num],
      rating,
    }));
    const { error: ansErr } = await supabase.from("response_answers").insert(answerRows);
    if (ansErr) throw ansErr;

    return {
      ok: true,
      message: updated ? "تم تحديث إجاباتك بنجاح" : "شكراً — تم حفظ إجاباتك بنجاح",
      updated,
    };
  }

  async function init() {
    if (!window.SUPABASE_URL || !window.SUPABASE_KEY) {
      showError("إعداد Supabase غير موجود. أنشئ docs/config.js من config.example.js");
      return;
    }

    supabase = window.supabase.createClient(window.SUPABASE_URL, window.SUPABASE_KEY);

    const { data: surveys, error } = await supabase
      .from("surveys")
      .select("*")
      .eq("is_active", true)
      .order("id", { ascending: false })
      .limit(1);

    if (error) {
      showError("تعذر الاتصال بقاعدة البيانات: " + error.message);
      return;
    }
    if (!surveys || !surveys.length) {
      showError("لا يوجد استبيان نشط.");
      return;
    }

    surveyRow = surveys[0];
    const { structure, total } = await loadSurveyStructure(surveyRow.id);

    const root = document.getElementById("app-root");
    root.innerHTML = renderSurvey(surveyRow, structure, total);
    root.classList.remove("is-hidden");
    document.getElementById("app-loading").classList.add("is-hidden");

    window.SURVEY_TOTAL = total;
    window.clinicSurveySubmit = submitAnswers;
    if (window.initSurveyUI) window.initSurveyUI();
  }

  init().catch(function (err) {
    showError(err.message || "حدث خطأ أثناء التحميل");
  });
})();
