// Builds the PatchAI project report (KIIT format) as a .docx.
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell, Header, Footer, AlignmentType,
  HeadingLevel, WidthType, ShadingType, BorderStyle, PageNumber, NumberFormat, TableOfContents, StyleLevel,
  LevelFormat, PageBreak, PositionalTab, PositionalTabAlignment, PositionalTabRelativeTo, PositionalTabLeader,
  VerticalAlign, TableLayoutType,
} = require("docx");

const FIG = path.join(__dirname, "fig");
const LOGO = path.join(__dirname, "assets", "kiit_logo.jpg");
const LOSS = path.join(__dirname, "..", "training", "runs", "v1", "loss.png");
const OUT = process.argv[2] || path.join(__dirname, "PatchAI_Project_Report.docx");

const FONT = "Times New Roman";
const MONO = "Courier New";
const W = 9026; // text width in DXA (A4, 1-inch margins)
const PROJECT = "PatchAI: Verified Repair of Security Vulnerabilities with a Fine-Tuned Small Language Model";
const SHORT = "PatchAI";

// ---------------------------------------------------------------- inline text
// **bold**, *italic*, `code`, [[placeholder]] (highlighted for the team to fill in)
function runs(text, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[\[[^\]]+\]\])/g;
  let last = 0, m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...base }));
    const t = m[0];
    if (t.startsWith("**")) out.push(new TextRun({ text: t.slice(2, -2), bold: true, ...base }));
    else if (t.startsWith("[[")) out.push(new TextRun({ text: t.slice(2, -2), highlight: "yellow", ...base }));
    else if (t.startsWith("*")) out.push(new TextRun({ text: t.slice(1, -1), italics: true, ...base }));
    else out.push(new TextRun({ text: t.slice(1, -1), font: MONO, size: 20, ...base }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  return out;
}

const body = [];
const add = (...xs) => body.push(...xs);
const P = (text, opts = {}) => new Paragraph({
  children: runs(text), alignment: AlignmentType.JUSTIFIED, spacing: { line: 360, after: 120 }, ...opts,
});
const p = (text, opts) => add(P(text, opts));
const bullets = (items, ref = "bullets") => items.forEach((t) => add(new Paragraph({
  children: runs(t), numbering: { reference: ref, level: 0 }, alignment: AlignmentType.JUSTIFIED,
  spacing: { line: 320, after: 60 },
})));
const numbered = (items) => bullets(items, "numbers");
const pageBreak = () => add(new Paragraph({ children: [new PageBreak()] }));

let chapterNo = 0;
let figNo = 0, tabNo = 0;
function chapter(title, first = false) {
  chapterNo += 1; figNo = 0; tabNo = 0;
  if (!first) pageBreak();
  add(new Paragraph({
    heading: HeadingLevel.HEADING_1,
    children: [new TextRun({ text: `Chapter ${chapterNo}` }), new TextRun({ text: title, break: 1 })],
  }));
}
function unnumberedChapter(title) {
  pageBreak();
  add(new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(title)] }));
}
const h2 = (t) => add(new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] }));
const h3 = (t) => add(new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(t)] }));

// ---------------------------------------------------------------- figures, tables, code
function pngSize(file) {
  const b = fs.readFileSync(file);
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) };
}
function figure(file, caption, widthIn = 6.2) {
  const { w, h } = pngSize(file);
  const width = Math.round(widthIn * 96);
  const height = Math.round(width * h / w);
  figNo += 1;
  add(new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { before: 120, after: 60 }, keepNext: true,
    children: [new ImageRun({ type: "png", data: fs.readFileSync(file), transformation: { width, height } })],
  }));
  add(new Paragraph({ style: "FigureCaption", children: runs(`Figure ${chapterNo}.${figNo}: ${caption}`) }));
  return `${chapterNo}.${figNo}`;
}
function placeholderFigure(what, caption) {
  if (caption) figNo += 1;
  const border = { style: BorderStyle.DASHED, size: 6, color: "999999" };
  add(new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { before: 120, after: 60 }, keepNext: true,
    border: { top: border, bottom: border, left: border, right: border },
    shading: { type: ShadingType.CLEAR, fill: "F7F7F5", color: "auto" },
    children: [new TextRun({ text: "", break: 3 }), ...runs(`[[${what}]]`), new TextRun({ text: "", break: 3 })],
  }));
  if (caption) add(new Paragraph({ style: "FigureCaption", children: runs(`Figure ${chapterNo}.${figNo}: ${caption}`) }));
}
const border = { style: BorderStyle.SINGLE, size: 4, color: "8C8C8C" };
const borders = { top: border, bottom: border, left: border, right: border };
function cell(text, width, { header = false, align = AlignmentType.LEFT, fill } = {}) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA }, borders, verticalAlign: VerticalAlign.CENTER,
    margins: { top: 50, bottom: 50, left: 90, right: 90 },
    shading: header ? { type: ShadingType.CLEAR, fill: "D9E2F3", color: "auto" }
      : fill ? { type: ShadingType.CLEAR, fill, color: "auto" } : undefined,
    children: [new Paragraph({ alignment: align, spacing: { line: 260 }, children: runs(String(text), { size: 20, bold: header || undefined }) })],
  });
}
// cols: [[title, relativeWidth, "l"|"c"|"r"], ...]; rows: arrays of strings
function table(caption, cols, rows, { highlightRows = [] } = {}) {
  tabNo += 1;
  add(new Paragraph({ style: "TableCaption", keepNext: true, children: runs(`Table ${chapterNo}.${tabNo}: ${caption}`) }));
  const total = cols.reduce((s, c) => s + c[1], 0);
  const widths = cols.map((c) => Math.floor(W * c[1] / total));
  widths[widths.length - 1] += W - widths.reduce((a, b) => a + b, 0);
  const al = (c) => ({ l: AlignmentType.LEFT, c: AlignmentType.CENTER, r: AlignmentType.RIGHT }[c[2] || "l"]);
  const trs = [new TableRow({ tableHeader: true, children: cols.map((c, i) => cell(c[0], widths[i], { header: true, align: al(c) })) })];
  rows.forEach((r, ri) => trs.push(new TableRow({
    cantSplit: true,
    children: r.map((v, i) => cell(v, widths[i], { align: al(cols[i]), fill: highlightRows.includes(ri) ? "EEF4FB" : (ri % 2 ? "F7F7F7" : undefined) })),
  })));
  add(new Table({ width: { size: W, type: WidthType.DXA }, columnWidths: widths, rows: trs, layout: TableLayoutType.FIXED }));
  add(new Paragraph({ spacing: { after: 120 }, children: [] }));
  return `${chapterNo}.${tabNo}`;
}
function code(lines) {
  lines.forEach((line, i) => add(new Paragraph({
    shading: { type: ShadingType.CLEAR, fill: "F3F3F1", color: "auto" },
    spacing: { line: 240, before: i === 0 ? 120 : 0, after: i === lines.length - 1 ? 160 : 0 },
    indent: { left: 240, right: 240 }, keepLines: true, keepNext: i < lines.length - 1,
    children: [new TextRun({ text: line || " ", font: MONO, size: 18 })],
  })));
}
const equation = (text) => add(new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { before: 120, after: 120 }, children: runs(text, { italics: true }),
}));

// ================================================================ FRONT MATTER
const front = [];
const C = (text, size, opts = {}) => new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { after: opts.after ?? 120, before: opts.before ?? 0 },
  children: [new TextRun({ text, size, bold: opts.bold, font: FONT, italics: opts.italics })],
});
const members = ["GROUP MEMBER A", "GROUP MEMBER B", "GROUP MEMBER C", "GROUP MEMBER D", "GROUP MEMBER E"];
const rolls = ["ROLL NUMBER A", "ROLL NUMBER B", "ROLL NUMBER C", "ROLL NUMBER D", "ROLL NUMBER E"];
function memberTable(bold) {
  const w1 = 5200, w2 = W - 5200;
  const nb = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
  const b = { top: nb, bottom: nb, left: nb, right: nb };
  return new Table({
    width: { size: W, type: WidthType.DXA }, columnWidths: [w1, w2], layout: TableLayoutType.FIXED,
    rows: members.map((m, i) => new TableRow({ children: [
      new TableCell({ width: { size: w1, type: WidthType.DXA }, borders: b, children: [new Paragraph({ alignment: AlignmentType.RIGHT, indent: { right: 400 }, children: [new TextRun({ text: m, bold, size: 26, highlight: "yellow" })] })] }),
      new TableCell({ width: { size: w2, type: WidthType.DXA }, borders: b, children: [new Paragraph({ children: [new TextRun({ text: rolls[i], size: 26, highlight: "yellow" })] })] }),
    ] })),
  });
}
const logo = (size = 110) => new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { before: 200, after: 200 },
  children: [new ImageRun({ type: "jpg", data: fs.readFileSync(LOGO), transformation: { width: size, height: size } })],
});
function titlePage(bold) {
  front.push(
    C("A PROJECT REPORT", 32, { bold, before: 600 }),
    C("on", 26, { bold }),
    C(`\u201C${PROJECT}\u201D`, 34, { bold, after: 300 }),
    C("Submitted to", 30, { bold }),
    C("KIIT Deemed to be University", 36, { bold, after: 240 }),
    C("In Partial Fulfilment of the Requirement for the Award of", 26, { bold }),
    C("BACHELOR\u2019S DEGREE IN", 30, { bold }),
    C("COMPUTER SCIENCE & ENGINEERING", 30, { bold, after: 300 }),
    C("BY", 30, { bold }),
    memberTable(bold),
    C("UNDER THE GUIDANCE OF", 26, { bold, before: 300 }),
    new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "GUIDE NAME", bold, size: 26, highlight: "yellow" })] }),
    logo(),
    C("SCHOOL OF COMPUTER SCIENCE AND ENGINEERING", 24, { bold }),
    C("KALINGA INSTITUTE OF INDUSTRIAL TECHNOLOGY", 30, { bold }),
    C("BHUBANESWAR, ODISHA - 751024", 24, { bold }),
    C("November 2026", 24, { bold }),
    new Paragraph({ children: [new PageBreak()] }),
  );
}
titlePage(true);
titlePage(false);

// Certificate
front.push(
  logo(90),
  C("KIIT Deemed to be University", 36),
  C("School of Computer Science and Engineering", 26),
  C("Bhubaneswar, ODISHA 751024", 26, { after: 400 }),
  C("CERTIFICATE", 44, { bold: true, after: 300 }),
  C("This is to certify that the project entitled", 26),
  C(`\u201C${PROJECT}\u201D`, 30, { bold: true }),
  C("submitted by", 26, { after: 200 }),
  memberTable(false),
  new Paragraph({
    alignment: AlignmentType.JUSTIFIED, spacing: { before: 300, line: 360 },
    children: runs("is a record of bonafide work carried out by them, in the partial fulfilment of the requirement for the award of the Degree of Bachelor of Engineering (Computer Science & Engineering or Information Technology) at KIIT Deemed to be University, Bhubaneswar. This work is done during the year 2026-2027, under our guidance.", { size: 26 }),
  }),
  new Paragraph({ spacing: { before: 600 }, children: [new TextRun({ text: "Date:      /      /", size: 26 })] }),
  new Paragraph({ alignment: AlignmentType.RIGHT, spacing: { before: 600 }, children: [new TextRun({ text: "(Guide Name)", size: 26, highlight: "yellow" })] }),
  new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "Project Guide", size: 26 })] }),
  new Paragraph({ children: [new PageBreak()] }),
);

// Acknowledgements
front.push(
  C("Acknowledgements", 40, { bold: true, after: 400, before: 200 }),
  new Paragraph({ alignment: AlignmentType.JUSTIFIED, spacing: { line: 360, after: 200 }, children: [
    new TextRun({ text: "We are profoundly grateful to ", size: 26 }), new TextRun({ text: "GUIDE NAME", size: 26, highlight: "yellow" }),
    new TextRun({ text: " of the School of Computer Science and Engineering, KIIT Deemed to be University, for expert guidance and continuous encouragement throughout this project, from its re-scoping as an AI-centred study to the evaluation of the final system.", size: 26 })] }),
  new Paragraph({ alignment: AlignmentType.JUSTIFIED, spacing: { line: 360, after: 200 }, children: runs("We also thank the maintainers of the open-source projects this work builds on, in particular Qwen2.5-Coder, Unsloth, Hugging Face TRL and PEFT, Ollama, Bandit, Semgrep and fastembed, and the authors of the CVEfixes dataset, whose curated record of real vulnerability fixes made the real-world part of our training data possible.", { size: 26 }) }),
  ...members.map((m) => new Paragraph({ alignment: AlignmentType.RIGHT, spacing: { before: 360 }, children: [new TextRun({ text: "Signature of  ", size: 26 }), new TextRun({ text: m, size: 26, highlight: "yellow" })] })),
  new Paragraph({ children: [new PageBreak()] }),
);

// Abstract
const absP = (t) => new Paragraph({ alignment: AlignmentType.JUSTIFIED, spacing: { line: 360, after: 200 }, children: runs(t, { size: 24 }) });
front.push(
  C("ABSTRACT", 40, { bold: true, after: 400, before: 200 }),
  absP("Injection flaws, path traversal, hard-coded credentials, weak cryptography and unsafe deserialisation remain among the most exploited weaknesses in deployed software. Static analysers detect such weaknesses reliably but do not repair them, while large language models (LLMs) can propose repairs but are typically used without verification, depend on hosted services that require source code to leave the developer\u2019s machine, or, in the case of small locally runnable models, are unreliable. This project presents **PatchAI**, a fully local, end-to-end system for the automated and verified repair of seven vulnerability classes (CWE-89, CWE-78, CWE-22, CWE-79, CWE-798, CWE-327 and CWE-502) in Python. PatchAI combines static detection (Bandit and custom Semgrep taint rules), hybrid retrieval-augmented generation (dense and BM25 retrieval, reciprocal rank fusion, cross-encoder re-ranking and call-graph-aware code retrieval), a Qwen2.5-Coder-3B model fine-tuned with QLoRA on prompts identical to those used at inference time, and a four-stage verification of every candidate patch (a safety guard, the project\u2019s own tests, an exploit-based security test and a re-scan) with execution-feedback retries and mandatory human approval."),
  absP("The system was evaluated on a purpose-built benchmark of 63 validated cases (53 test cases), each guaranteed to be detectable, exploitable and solvable. Under an identical pipeline, task-specific fine-tuning raised the verified fix rate of the 3B model from 41.5% (95% Wilson interval 29.3\u201354.9%) to 79.2% (66.5\u201388.0%), produced 100% schema-valid outputs, reduced the mean time per case by 30%, and fixed 6 of 7 hand-written cases; the 2.3\u00D7 larger 7B base model reached 92.5% (82.1\u201397.0%). A systematic analysis of every recorded attempt revealed a scoring artefact that had understated the 7B model by 18 percentage points, two failure modes induced by the training data, and retries that rarely changed the model\u2019s answer. A second iteration (v2) addressed each finding, including 21 real CVE fixes from the CVEfixes dataset filtered by our own scanners. Measured in a single four-model run, v2 reached 86.8% (75.2–93.5%) against 71.7% for v1 and 90.6% for the 7B base model, statistically indistinguishable from the larger model while being about three times faster per case. The results indicate that verification-centred design and evidence-driven error analysis matter as much as model size for trustworthy automated vulnerability repair."),
  new Paragraph({ spacing: { before: 200 }, alignment: AlignmentType.JUSTIFIED, children: [
    new TextRun({ text: "Keywords: ", bold: true, size: 24 }),
    new TextRun({ text: "Automated vulnerability repair; large language models; QLoRA fine-tuning; retrieval-augmented generation; static analysis; software security; Common Weakness Enumeration.", size: 24 })] }),
  new Paragraph({ children: [new PageBreak()] }),
);

// Contents, figures, tables
const listTitle = (t) => new Paragraph({ spacing: { after: 300 }, children: [new TextRun({ text: t, size: 40, bold: true })] });
front.push(
  listTitle("Contents"),
  new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-3" }),
  new Paragraph({ children: [new PageBreak()] }),
  listTitle("List of Figures"),
  new TableOfContents("Figures", { hyperlink: true, stylesWithLevels: [new StyleLevel("FigureCaption", 1)] }),
  new Paragraph({ children: [new PageBreak()] }),
  listTitle("List of Tables"),
  new TableOfContents("Tables", { hyperlink: true, stylesWithLevels: [new StyleLevel("TableCaption", 1)] }),
);

// ================================================================ CHAPTER 1
chapter("Introduction", true);
p("Software vulnerabilities are defects that let an attacker make a program do something its authors did not intend: read another user\u2019s data through an injected SQL fragment, run operating-system commands through an unsanitised argument, or execute code by uploading a crafted serialised object. The Common Weakness Enumeration (CWE) [1] catalogues these weaknesses, and the OWASP Top 10 [2] shows that injection, broken cryptography and insecure design have remained among the most critical risks for web applications for more than a decade. The problem is not a lack of detection: mature static analysers such as Bandit [23] and Semgrep [24] flag many of these patterns within seconds. The bottleneck is **repair**. Every finding still has to be understood, fixed correctly, and checked by a developer, and the gap between \u201Cdetected\u201D and \u201Cfixed\u201D is where vulnerabilities survive.");
p("Large language models trained on source code can write plausible patches for such findings, and early studies showed that general-purpose models can repair a meaningful share of security bugs in a zero-shot setting [8]. However, three gaps separate this capability from something a developer can trust. First, the strongest models are hosted services, so using them means sending proprietary source code to a third party, which many organisations cannot do. Second, small models that run on a laptop are markedly less reliable, and their output format is often not even machine-readable. Third, and most importantly, model-generated patches are rarely **verified**: a patch that silences the scanner may still be exploitable, and a patch that removes the vulnerability may break the program. Evaluations that only check whether a scanner is satisfied, or whether the output matches a reference patch textually, overstate how often the fix is actually correct.");
p("This project addresses these gaps with **PatchAI**, a local system that treats repair as a pipeline of separately accountable steps rather than a single model call. A scanner finds the vulnerability; a hybrid retrieval-augmented generation (RAG) component gathers a security guide for the weakness, the project\u2019s own helper functions and similar past fixes; a small model that we fine-tuned for exactly this task writes the fixed function in a strict JSON format; and the candidate patch is accepted only if it passes a safety guard, the project\u2019s own tests, an *exploit-based security test* that performs the real attack, and a re-scan, all on a temporary copy of the project. Failed attempts are fed back to the model with the exact error, and nothing changes in the real project until a human approves the diff in a review application or in Visual Studio Code.");
p("The work is framed as an empirical study as well as a system. We ask whether task-specific parameter-efficient fine-tuning makes a 3-billion-parameter model competitive for verified repair, how it compares with a 2.3\u00D7 larger model of the same family, and what remains wrong after fine-tuning. The main contributions are:");
bullets([
  "**An end-to-end, fully local repair pipeline** for seven CWE classes in Python, combining static detection, hybrid RAG, a fine-tuned small language model and four-stage verification with execution-feedback retries and human approval.",
  "**A verification protocol based on real exploits.** Every fix must make an attack test pass, which exposes \u201Cfake fixes\u201D that satisfy the scanner but remain exploitable.",
  "**A training-data pipeline** that produces prompts identical to inference prompts (real scanner findings, real retrieval) from synthetic vulnerable/fixed pairs and from real CVE fixes reconstructed from the CVEfixes dataset [9].",
  "**A validated benchmark** of 63 cases in which every case is confirmed to be detectable, exploitable and solvable, and a controlled comparison of a fine-tuned 3B model with its base model and a 7B base model, reported with 95% confidence intervals.",
  "**An evidence-driven error analysis and second iteration** that identifies a measurement artefact, two data-induced failure modes and ineffective retries, and addresses each of them.",
]);
p("The remainder of this report is organised as follows. Chapter 2 introduces the concepts and reviews related work on vulnerability detection, automated program repair, efficient fine-tuning and retrieval-augmented generation. Chapter 3 states the problem and the research questions, and presents the requirements and the system design. Chapter 4 describes the implementation, the verification plan and the experimental results, including the error analysis that motivated the second iteration. Chapter 5 lists the standards adopted and a cost analysis, and Chapter 6 concludes with the limitations and future scope.");

// ================================================================ CHAPTER 2
chapter("Basic Concepts / Literature Review");
p("This chapter introduces the concepts that the rest of the report relies on and positions PatchAI with respect to prior work. Section 2.1 defines the vulnerability classes in scope; Sections 2.2 to 2.6 cover static analysis, automated repair, code language models, efficient fine-tuning and retrieval; Section 2.7 discusses self-correction with execution feedback; and Section 2.8 summarises the research gap.");
h2("2.1 Software Vulnerabilities and the CWE Taxonomy");
p("A vulnerability is a weakness that an attacker can exploit to violate confidentiality, integrity or availability. The MITRE CWE list [1] gives each class of weakness a stable identifier, which lets tools, guides and datasets refer to the same concept. PatchAI targets seven classes that are common in Python web and scripting code and that have a well-understood correct fix (Table 2.1).");
table("Vulnerability classes in scope", [["CWE", 0.9, "c"], ["Name", 2.2], ["What an attacker can do", 3.4], ["Typical correct fix", 3.3]], [
  ["CWE-89", "SQL injection", "read or modify the database by injecting SQL", "parameterised queries"],
  ["CWE-78", "OS command injection", "run arbitrary commands on the server", "argument lists without a shell"],
  ["CWE-22", "Path traversal", "read or write files outside the intended folder", "resolve the path and check containment"],
  ["CWE-79", "Cross-site scripting", "run script in other users\u2019 browsers", "context-aware output escaping"],
  ["CWE-798", "Hard-coded credentials", "recover secrets from the source code", "load secrets from the environment"],
  ["CWE-327", "Broken or risky cryptography", "forge, predict or brute-force hashes and keys", "SHA-256, HMAC, PBKDF2, secrets module"],
  ["CWE-502", "Deserialisation of untrusted data", "execute code via crafted serialised input", "JSON or safe YAML loaders"],
]);
p("The following example from the project\u2019s demonstration application shows the typical shape of such a weakness and its repair. The vulnerable version builds SQL by string interpolation, so the input `' OR '1'='1` returns every row; the repaired version passes the input as a parameter, so it can never become part of the SQL text.");
code([
  "# Vulnerable (CWE-89): user input becomes part of the SQL text",
  "sql = f\"SELECT * FROM products WHERE name LIKE '%{term}%'\"",
  "return run_query(conn, sql)",
  "",
  "# Repaired: the input is a parameter, never part of the SQL",
  "sql = \"SELECT * FROM products WHERE name LIKE ?\"",
  "return run_query(conn, sql, (f\"%{term}%\",))",
]);
h2("2.2 Static Analysis for Security");
p("Static application security testing (SAST) inspects source code without running it. Bandit [23] parses Python into an abstract syntax tree (AST) and applies plugin rules, for example rule B608 for SQL assembled with string formatting or B602 for `subprocess` calls with `shell=True`. Rule-based checks of this kind are fast and precise for local patterns but cannot see data flow: whether a value that reaches `open()` came from an HTTP request. Semgrep [24] supports *taint analysis*, in which a rule declares sources (where untrusted data enters), sinks (where it becomes dangerous) and sanitisers; a finding is reported when data flows from a source to a sink without passing a sanitiser. PatchAI uses Bandit for the five classes it covers well and two custom Semgrep taint rules for path traversal and reflected XSS, which Bandit cannot detect.");
h2("2.3 Automated Program Repair and Vulnerability Repair");
p("Automated program repair (APR) generates patches that make a failing program pass its specification, usually a test suite [4]. Search-based techniques such as GenProg [3] mutate the program and keep variants that pass more tests; their well-known weakness is *overfitting*: patches that pass the tests without being correct. Learning-based vulnerability repair followed: VRepair [5] used transfer learning from bug-fix data to security fixes in C, and VulRepair [6] fine-tuned a T5 model on vulnerability-fix pairs. These works mostly evaluate by exact match with a reference patch, which underestimates semantically correct alternatives and says nothing about exploitability. With the arrival of large code models, Pearce *et al.* first showed that assistants such as Copilot frequently generate vulnerable code [7], and then that LLMs can repair a share of security bugs in a zero-shot setting when given a well-designed prompt [8]. Conversational repair approaches such as ChatRepair [21] add test feedback to the dialogue. Benchmarks such as SWE-bench [29] emphasise execution-based evaluation, which is the stance PatchAI adopts for security repair.");
h2("2.4 Language Models for Code");
p("Code language models are transformer models pre-trained on large corpora of source code and natural language. The Qwen2.5-Coder family [10] provides instruction-tuned models from 0.5 to 32 billion parameters with strong results on code generation and repair benchmarks. Models of 3 to 7 billion parameters can run on a consumer laptop when quantised to 4 bits, for example in the GGUF format served by Ollama [25] through llama.cpp [27]. Their limited capacity, however, makes them sensitive to prompt format and prone to inventing functions or packages (\u201Challucination\u201D), which motivates both task-specific fine-tuning and grounding through retrieval.");
h2("2.5 Parameter-Efficient Fine-Tuning and Preference Optimisation");
p("Full fine-tuning updates every weight of a model and is infeasible on an 8 GB GPU for a 3B model. Low-Rank Adaptation (LoRA) [11] freezes the pre-trained weights W and learns a low-rank update \u0394W = BA, where B and A have rank r much smaller than the layer dimensions, so that only a few million parameters are trained. QLoRA [12] additionally stores the frozen base model in 4-bit NormalFloat precision and back-propagates through it into the LoRA adapters, which makes fine-tuning of multi-billion-parameter models possible on a single consumer GPU. Supervised fine-tuning (SFT) teaches the model to imitate target answers; Direct Preference Optimization (DPO) [13] further trains it to prefer a \u201Cchosen\u201D answer over a \u201Crejected\u201D one without a separate reward model. PatchAI uses QLoRA SFT as its main training method and DPO, with the model\u2019s own failed fixes as rejected answers, as an optional second stage. Training uses the Unsloth library together with Hugging Face TRL [26] and PEFT.");
h2("2.6 Retrieval-Augmented Generation");
p("Retrieval-augmented generation [14] supplies a model with documents retrieved for the current query, so that it can rely on information that is not stored in its weights. Two retrieval families are complementary. Sparse retrieval with BM25 [15] scores documents by term overlap and is precise for exact identifiers such as `run_query` or `yaml.safe_load`. Dense retrieval embeds queries and documents into a vector space, here with BGE-small [18], and finds paraphrases with no shared terms. Reciprocal rank fusion (RRF) [16] merges ranked lists without calibrating their scores:");
equation("RRF(d) = \u03A3 over lists r of  1 / (k + rank_r(d)),   with k = 60");
p("A cross-encoder re-ranker [17], trained on the MS MARCO passage-ranking data [30], then reads the query and each candidate together and re-scores the best candidates. This two-stage design, cheap recall followed by precise re-ranking, is standard in modern retrieval.");
h2("2.7 Self-Correction with Execution Feedback");
p("Models often fail on the first attempt but succeed when shown why they failed. Self-Debug [19] feeds execution results back to the model, and Reflexion [20] stores verbal feedback from failed trials to guide later ones. The effectiveness of such loops depends on the *quality* of the feedback: an uninformative error message gives the model nothing to act on. This observation turned out to be central in our own results (Section 4.3), where vague errors led the model to repeat the same wrong answer.");
h2("2.8 Research Gap");
p("Table 2.2 compares representative approaches with PatchAI. Prior learning-based vulnerability repair mostly targets C, evaluates by textual similarity, and does not check exploitability; LLM-based repair typically relies on large hosted models. To our knowledge, the combination studied here (a small, locally fine-tuned model, hybrid retrieval and exploit-based verification of every patch, evaluated against a larger model under an identical pipeline) has not been reported for Python security repair.");
table("Comparison of PatchAI with related approaches", [["Approach", 2.0], ["Repair technique", 2.6], ["How a fix is judged", 2.6], ["Local", 0.8, "c"], ["Language", 1.1, "c"]], [
  ["GenProg [3]", "search over program mutations", "test suite", "yes", "C"],
  ["VRepair [5]", "transformer, transfer learning", "match with reference patch", "yes", "C"],
  ["VulRepair [6]", "fine-tuned T5", "match with reference patch", "yes", "C/C++"],
  ["Zero-shot LLM repair [8]", "prompting large LLMs", "tests and scanner", "no", "C, Verilog"],
  ["ChatRepair [21]", "conversational LLM with test feedback", "test suite", "no", "Java, Python"],
  ["**PatchAI (this work)**", "QLoRA fine-tuned 3B model + hybrid RAG + feedback retries", "guard, tests, exploit test and re-scan; human approval", "yes", "Python"],
], { highlightRows: [5] });

// ================================================================ CHAPTER 3
chapter("Problem Statement / Requirement Specifications");
p("**Problem statement.** Given a Python project and a vulnerability reported by a static analyser, produce a minimal source-code change that removes the vulnerability, preserves the program\u2019s intended behaviour, and can be shown to do both, using only resources that run on a developer\u2019s laptop, and present it to a human for approval. The quality of a solution is measured by its *verified fix rate*: the fraction of vulnerabilities for which the proposed patch passes the project\u2019s tests, defeats a concrete exploit and is no longer reported by the scanner.");
p("Within this problem, the study answers three research questions:");
bullets([
  "**RQ1 (effect of fine-tuning).** Does task-specific QLoRA fine-tuning of a 3B code model improve its verified fix rate under an identical retrieval and verification pipeline, and how does the fine-tuned model compare with a 2.3\u00D7 larger base model of the same family?",
  "**RQ2 (residual failures).** Which failure modes remain after fine-tuning, and what are their root causes?",
  "**RQ3 (targeted improvement).** Can changes to the training data, the prompt and the scoring, derived from the error analysis, remove those failure modes in a second iteration?",
]);
h2("3.1 Project Planning");
p("The project replaced an earlier design that focused on hosting infrastructure (databases, task queues and container orchestration) with an AI-centred design whose results can be measured. Work was planned in six phases (Table 3.1); the team roles are listed in Table 3.2. Model training and evaluation ran on a team member\u2019s RTX 4060 laptop, while all other development used ordinary laptops, which the design deliberately allows.");
table("Project phases and deliverables", [["Phase", 1.7], ["Main activities", 4.2], ["Deliverable", 2.6], ["Status", 1.2, "c"]], [
  ["1. Re-scoping", "replace the infrastructure-heavy design; define scope (7 CWEs, Python, local)", "project plan, research questions", "done"],
  ["2. Pipeline", "scanner, context, RAG, prompt, verification, review; scripted test model", "working pipeline, automated tests", "done"],
  ["3. Data and benchmark", "synthetic generator, dataset builder, validated benchmark, demo application", "training data, 63-case benchmark", "done"],
  ["4. Training and evaluation (v1)", "QLoRA SFT on the GPU laptop; 3-model comparison", "patchai-3b v1, results", "done"],
  ["5. Error analysis and v2", "read every attempt; fix scoring, data and retries; add CVEfixes data", "v2 code, re-scored v1, v2 model", "done"],
  ["6. Reporting", "report, presentation, demonstration rehearsal", "this report, demo", "in progress"],
]);
table("Team roles", [["Member", 1.8], ["Area of ownership", 3.2], ["Main modules", 4.0]], [
  ["[[GROUP MEMBER A]]", "Training", "training/ (data generation, SFT, export, DPO)"],
  ["[[GROUP MEMBER B]]", "Retrieval (RAG)", "rag_index.py, rag_search.py, embeddings.py, knowledge base"],
  ["[[GROUP MEMBER C]]", "Model and fixing", "prompts.py, llm.py, fixer.py, patching.py, pipeline.py"],
  ["[[GROUP MEMBER D]]", "Detection and checks", "scan.py, context.py, guard.py, checks.py, Semgrep rules, demo project"],
  ["[[GROUP MEMBER E]]", "Interfaces and evaluation", "review app, VS Code extension, server, eval/, metrics.py"],
]);
h2("3.2 Project Analysis");
p("The requirements were derived from the problem statement and refined by removing ambiguities. *Which* vulnerabilities: seven CWE classes with an established correct fix. *What* the model may change: exactly one function, or one statement at module level, so that a fix is reviewable and cannot silently modify unrelated code. *When* a fix counts as correct: only when all checks pass; scanner silence alone is insufficient. *Where* code is executed: only on a temporary copy, never in the user\u2019s project. Tables 3.3 and 3.4 list the resulting functional and non-functional requirements.");
table("Functional requirements", [["ID", 0.7, "c"], ["Requirement", 5.4], ["Realised in", 2.6]], [
  ["FR-1", "Detect vulnerabilities of the seven classes in a Python project and report CWE, file, line and rule", "scan.py, semgrep_rules.yaml"],
  ["FR-2", "Extract the code region the model may rewrite (enclosing function), its imports and called functions", "context.py"],
  ["FR-3", "Retrieve relevant security guidance, project code and similar past fixes for each finding", "rag_index.py, rag_search.py"],
  ["FR-4", "Generate a fix as structured output, or state that the code cannot be fixed safely or is a false alarm", "prompts.py, llm.py"],
  ["FR-5", "Verify each fix with a safety guard, the project\u2019s tests, an exploit-based security test and a re-scan", "guard.py, checks.py"],
  ["FR-6", "Retry a failed fix, giving the model its previous fix and the exact error (at most three attempts)", "fixer.py"],
  ["FR-7", "Apply a fix only after human approval and log every decision", "review.py"],
  ["FR-8", "Compare several models on the same vulnerability", "review app"],
  ["FR-9", "Evaluate models on a benchmark and report fix rates with confidence intervals", "eval/, metrics.py"],
  ["FR-10", "Offer the workflow inside Visual Studio Code", "extension/, server.py"],
]);
table("Non-functional requirements", [["ID", 0.8, "c"], ["Quality", 1.6], ["Requirement", 6.3]], [
  ["NFR-1", "Privacy", "No source code leaves the machine: local models, local embeddings, no cloud services"],
  ["NFR-2", "Safety", "Candidate patches run only in a temporary copy; the project changes only after approval"],
  ["NFR-3", "Explainability", "Every result shows the diff, the explanation, each attempt\u2019s checks and the retrieved context"],
  ["NFR-4", "Reproducibility", "Training and evaluation runs record settings, dataset hashes, prompt version and commit"],
  ["NFR-5", "Performance", "A fix attempt completes in seconds on the GPU laptop and in minutes on a CPU-only laptop"],
  ["NFR-6", "Maintainability", "One module per pipeline step; automated tests that need no model or GPU"],
  ["NFR-7", "Portability", "Runs on Windows and Linux (WSL2 for training)"],
]);
h2("3.3 System Design");
h3("3.3.1 Design Constraints");
p("The design is shaped mainly by the available hardware. Training had to fit in the 8 GB of video memory of a laptop RTX 4060, which rules out full fine-tuning and favours 4-bit QLoRA with a sequence length of 4,096 tokens. Inference must also run on CPU-only laptops for demonstrations, so the model is exported as a 4-bit GGUF file and served by Ollama. The prompt, including retrieved context, must fit in the 8,192-token inference context; it measures about 2,000 tokens on average. Table 3.5 summarises the environment.");
table("Hardware and software environment", [["Item", 2.2], ["Specification", 6.8]], [
  ["Training machine", "Laptop with NVIDIA GeForce RTX 4060 (8 GB VRAM), Windows 11 with WSL2 Ubuntu"],
  ["Development and demo machines", "Ordinary laptops (CPU inference through Ollama)"],
  ["Language and runtime", "Python 3.11; TypeScript for the VS Code extension"],
  ["Models", "Qwen2.5-Coder-3B-Instruct (fine-tuned); Qwen2.5-Coder 3B and 7B (baselines), 4-bit quantised"],
  ["Training stack", "PyTorch (CUDA 12.4), Unsloth, Hugging Face TRL, PEFT, bitsandbytes, llama.cpp (GGUF export)"],
  ["Serving", "Ollama with JSON-schema-constrained structured output"],
  ["Retrieval", "fastembed (ONNX): BAAI/bge-small-en-v1.5 embeddings, MiniLM-L-6 cross-encoder; rank-bm25; NumPy"],
  ["Detection", "Bandit; Semgrep with two custom taint rules"],
  ["Interfaces", "Streamlit, FastAPI (local only), VS Code extension API, Typer CLI"],
  ["Evaluation", "pytest, pandas, matplotlib"],
]);
h3("3.3.2 System Architecture");
p("Figure 3.1 shows the architecture. The online pipeline (centre) consists of five stages: detection, retrieval, generation, verification and human review. It is supported by a knowledge base (left) and by a model produced by an offline training pipeline (right). A failed verification returns to generation with the previous fix and the exact error; a successful one goes to human review.");
figure(path.join(FIG, "architecture.png"), "System architecture of PatchAI: the online repair pipeline, the knowledge base and the offline training pipeline", 5.6);
p("Each stage is implemented as one module with one responsibility (Table 3.6), so that it can be tested and explained in isolation. The pipeline entry point `fix_finding()` never raises an exception: every failure becomes a reported verdict, which keeps the user interfaces and the evaluation simple.");
table("Components and their responsibilities", [["Module", 2.0], ["Responsibility", 7.0]], [
  ["scan.py", "Runs Bandit and Semgrep; maps rules to CWE classes; returns Findings"],
  ["context.py", "Uses the Python AST to extract the enclosing function, imports and called functions"],
  ["rag_index.py / rag_search.py", "Builds the guide, past-fix and code collections; hybrid search, fusion, re-ranking"],
  ["prompts.py", "Builds the prompt; shared with training so that both always match (versioned)"],
  ["llm.py", "The only module that calls a model (Ollama), with JSON-schema-constrained output"],
  ["patching.py", "Cleans the model\u2019s code, splices it into the file, adds imports, computes the diff"],
  ["guard.py / checks.py", "Safety rules; tests, exploit test and re-scan on a temporary copy"],
  ["fixer.py / pipeline.py", "The attempt-and-retry loop; the end-to-end entry point for one finding"],
  ["review.py", "Approval, rejection and the decision log"],
  ["app/, extension/, server.py, cli.py", "Streamlit review app, VS Code extension, local API and command line"],
]);
p("Figure 3.2 details the retrieval stage. The query, consisting of the scanner message and the vulnerable function, is sent to a dense and a sparse retriever; their rankings are fused with RRF and the best candidates are re-ranked by a cross-encoder. Each of the three collections is queried separately, so that the prompt always contains two security-guide chunks, two project-code chunks and two past fixes.");
figure(path.join(FIG, "rag.png"), "Hybrid retrieval: dense and sparse search, reciprocal rank fusion and cross-encoder re-ranking", 6.2);

// ================================================================ CHAPTER 4
chapter("Implementation");
p("This chapter presents the implementation of PatchAI and its evaluation. Section 4.1 describes the method stage by stage, including the training data and the fine-tuning; Section 4.2 the verification plan and the benchmark; Section 4.3 the results and the error analysis; and Section 4.4 the quality-assurance measures.");
h2("4.1 Methodology");
p("The project followed an iterative, evidence-driven method (Figure 4.1). After building the pipeline, the data and the benchmark, a first model (v1) was trained and evaluated against two baselines. Every recorded attempt was then read to find the causes of failure, and the findings drove a second iteration (v2) of the data, the prompt and the scoring.");
figure(path.join(FIG, "method.png"), "Research method: build, train, evaluate, analyse and improve", 6.2);
h3("4.1.1 Vulnerability Detection");
p("Bandit is run with only the rules that map to the seven classes, and each rule is mapped to a CWE identifier (Table 4.1). Two Semgrep taint rules written for this project cover path traversal (a function argument joined onto a directory and passed to `open()` or `send_file()` without a containment check) and reflected XSS (request data returned in an HTML response without escaping). Findings from both tools are merged and de-duplicated, and every class receives a fixed severity so that both scanners rank findings consistently. Directories containing tests are excluded, because test code deliberately contains attack strings.");
table("Detection rules per vulnerability class", [["CWE", 1.0, "c"], ["Detector and rules", 4.4], ["Example pattern detected", 3.6]], [
  ["CWE-89", "Bandit B608", "SQL assembled with f-strings, % or +"],
  ["CWE-78", "Bandit B602, B604, B605", "shell=True, os.system, os.popen with input"],
  ["CWE-22", "Semgrep taint rule path-traversal-open", "os.path.join(folder, arg) reaching open()"],
  ["CWE-79", "Semgrep taint rule flask-reflected-xss; Bandit B308, B701, B703", "request data returned as HTML; mark_safe; Jinja2 without autoescape"],
  ["CWE-798", "Bandit B105, B106, B107", "password-like names assigned or compared to literals"],
  ["CWE-327", "Bandit B303, B324", "MD5 or SHA-1 used for security"],
  ["CWE-502", "Bandit B301, B302, B506", "pickle, marshal, yaml.load without a safe loader"],
]);
h3("4.1.2 Context Extraction");
p("For each finding, `context.py` parses the file with Python\u2019s `ast` module and selects the innermost function (including decorators) that contains the flagged line; module-level findings such as a hard-coded constant use the enclosing statement instead. The region\u2019s indentation is recorded so that a fixed method can be re-inserted inside its class. The file\u2019s top-level imports and the names of the functions the region calls are also extracted; the latter drive the call-graph-aware code retrieval described next. Restricting the model to one region is a deliberate safety decision: the rest of the file is never sent to be rewritten.");
h3("4.1.3 Hybrid Retrieval");
p("The knowledge base consists of seven security guides written for this project (one per CWE), 35 curated before-and-after fixes, and an index of every function in the project being repaired. Documents are chunked to at most 1,500 characters and embedded with BGE-small (384 dimensions); vectors are stored as NumPy arrays rather than in a database, since a few thousand chunks require no server. For each collection, the dense and BM25 retrievers each return 20 candidates, which are fused with RRF (k = 60) and re-ranked with the cross-encoder. Guides and past fixes are filtered to the finding\u2019s CWE. For project code, functions that the vulnerable function calls are ranked first, because a correct fix usually needs the project\u2019s own helpers (for example a `run_query(conn, sql, params)` wrapper) rather than an invented one. The top two chunks of each collection enter the prompt.");
h3("4.1.4 Prompt Design and Output Contract");
p("The prompt states the finding (CWE, scanner rule, message, location, flagged line), the file\u2019s imports, the six retrieved chunks and the vulnerable region. Untrusted text is wrapped in tags (`<reference>`, `<vulnerable_code>`, `<previous_fix>`, `<error>`), and the system prompt instructs the model that text inside these tags is data, not instructions, which mitigates prompt injection through code comments or documents. Seven rules constrain the answer, among them: keep the function\u2019s name, parameters and behaviour; make the smallest change; use only the standard library or existing imports; never add `# nosec`, `eval`, `exec` or `shell=True`; and answer \u201Cfalse_positive\u201D or \u201Ccannot_fix\u201D rather than guess. The model must reply with a JSON object that Ollama enforces through a JSON schema:");
code([
  "{\"status\": \"fixed\" | \"cannot_fix\" | \"false_positive\",",
  " \"fixed_code\": \"<the complete fixed function>\",",
  " \"imports_to_add\": [\"import ...\"],",
  " \"explanation\": \"<one or two sentences for the reviewer>\",",
  " \"confidence\": <number between 0 and 1>}",
]);
p("The model returns the whole fixed function rather than a diff, because small models frequently produce malformed diffs. `patching.py` removes any wrapping (markdown fences, and, since v2, prompt tags the model may echo), re-indents the code, splices it into the file, inserts new imports below the existing ones and computes the diff itself, preserving the file\u2019s original line endings. The prompt module carries a version number (v1, then v2) that is recorded with every dataset and evaluation run, because the fine-tuned model is trained on exactly this format.");
h3("4.1.5 Training Data");
p("**Synthetic pairs.** A generator (`synth.py`) defines code *families*: common Python patterns written twice, once vulnerable and once correctly fixed, with randomised entity names, field names, query styles, docstrings and helper functions, so that thousands of distinct examples arise and every label is correct by construction. Three further families produce *false alarms*, safe code that a scanner flags anyway, labelled \u201Cfalse_positive\u201D. Crucially, the dataset builder (`make_dataset.py`) does not format these pairs itself: it writes each example to a file, runs the real scanners, extracts the region with the real context module, performs the real retrieval and builds the prompt with the same function used at inference time. Examples the scanners do not detect are dropped. The training prompts are therefore identical in distribution to the prompts the model sees in use. A share of examples are *retry* examples, whose prompt contains a failed previous attempt and its error, and whose answer is the correct fix.");
p("**Version 1 and version 2.** The v1 dataset contained 2,500 examples (2,250 for training, 250 for validation; median prompt length about 2,036 tokens). The error analysis in Section 4.3 revealed that a sampling defect had made 643 examples (25.7%) false alarms, 623 of them from a single pattern, and had left command injection with only 72 vulnerable examples. Version 2 assigns a fixed quota to every class and exactly 8% to false alarms, adds variety where a family had few distinct variants, and adds two families that teach concepts v1 lacked (Section 4.3.5). It also raises the share of retry examples to 20% and makes them realistic: the prompt shows a typical wrong fix for the pattern together with the exact error our checks report for it. Figure 4.2 and Table 4.2 compare the two versions.");
figure(path.join(FIG, "data_composition.png"), "Training examples per vulnerability class in v1 and v2 (v2: synthetic plus real CVE fixes, the latter counted twice)", 6.2);
table("Training data, v1 and v2", [["Property", 3.4], ["v1", 2.6, "c"], ["v2", 3.0, "c"]], [
  ["Synthetic examples", "2,500", "2,500"],
  ["Real-world examples (CVEfixes)", "0", "21 (each used twice)"],
  ["Vulnerable code families / false-alarm families", "20 / 3", "22 / 3"],
  ["False alarms", "643 (25.7%)", "200 (8.0%)"],
  ["Command-injection examples", "72", "320 + 4 real"],
  ["Retry examples", "286, generic error messages", "about 20%, typical mistake + exact error + previous fix"],
  ["Hard-coded secret fixes", "two thirds os.environ[\"X\"]", "always os.environ.get(\"X\", \"\")"],
  ["Prompt version", "v1", "v2 (retry shows the previous fix)"],
]);
p("**Real-world data.** To complement the synthetic data with real code, we used CVEfixes [9], a dataset that links published CVEs to the commits that fixed them (Hugging Face release of CVEfixes v1.0.8, Apache-2.0). The dataset stores only the changed lines, not whole functions, so `real_data.py` rebuilds them: for each of the 162 Python fixes in our seven classes, it downloads every changed file from GitHub at the fixing commit and applies the commit\u2019s diff in reverse to recover the vulnerable version (334 files were rebuilt exactly). Our own scanners are then run on both versions, and a finding becomes a training example only if it lies inside a function that the commit changed **and** the fixed version of that function is no longer flagged. Further filters keep the examples consistent with what the pipeline can accept (same signature, at most 30 changed lines, no new third-party imports or helper functions) and remove fixes that would teach a wrong lesson, such as a fix that still used `shell=True` or `yaml.full_load`. As Figure 4.3 shows, real fixes are noisy and most findings are filtered out; 21 examples from 14 CVEs in 14 different projects remain, including security patches to Django, Gradio, ParlAI, Nautobot and WsgiDAV.");
figure(path.join(FIG, "cvefixes_filter.png"), "Filtering of scanner findings in the rebuilt CVEfixes files", 5.8);
h3("4.1.6 Fine-Tuning");
p("The base model is Qwen2.5-Coder-3B-Instruct. Training uses QLoRA through Unsloth and TRL\u2019s supervised fine-tuning trainer, with the loss computed on the assistant\u2019s answer only, so that the model learns to write fixes rather than to reproduce prompts. Table 4.3 lists the hyper-parameters. The v1 model trained for 115.5 minutes on the RTX 4060. Its training loss fell steeply during the first 50 optimiser steps and the validation loss stabilised at 0.034 (Figure 4.4), with no divergence between training and validation loss. A very low validation loss on synthetic data indicates that the format and the patterns were learned, but not necessarily that the skill generalises, which is why the evaluation uses different code patterns.");
table("Fine-tuning configuration", [["Setting", 3.0], ["Value", 2.4], ["Reason", 3.6]], [
  ["Method", "QLoRA (4-bit base, LoRA)", "fits a 3B model in 8 GB of VRAM"],
  ["LoRA rank / alpha / dropout", "16 / 32 / 0", "standard for task adaptation"],
  ["Target modules", "q, k, v, o, gate, up, down", "all attention and MLP projections"],
  ["Maximum sequence length", "4,096 tokens", "prompts average about 2,000 tokens"],
  ["Epochs", "2", "learns format and patterns without memorising templates"],
  ["Learning rate / schedule", "2e-4 / cosine, 3% warm-up", "common values for LoRA SFT"],
  ["Batch size \u00D7 gradient accumulation", "2 \u00D7 8 = 16", "memory limit; automatic fallback 1 \u00D7 16"],
  ["Optimiser", "8-bit AdamW, weight decay 0.01", "reduces optimiser memory"],
  ["Loss", "assistant answer tokens only", "the model learns to answer, not to copy prompts"],
  ["Export", "GGUF q4_k_m, served by Ollama", "runs on GPU and CPU-only laptops"],
]);
figure(LOSS, "Training and validation loss of the v1 fine-tuning run", 5.6);
p("**Optional preference optimisation.** `dpo.py` implements a DPO stage: the SFT model writes four fixes for each of 400 new training cases at a higher temperature, our checks label each one, and every failing fix becomes a *rejected* answer paired with the correct fix as *chosen*. DPO then trains a new adapter on top of the merged SFT model, using the frozen SFT model as the reference. This stage is included in the automated run as an option.");
h3("4.1.7 Verification and Feedback Loop");
p("A candidate fix is first checked by a safety guard that requires no execution (Table 4.4). It is then applied to a temporary copy of the project, where three executed checks run: the project\u2019s own tests (no test that passed before may fail), the security test for the finding\u2019s class, and a re-scan of the file (the finding must disappear and no new finding may appear). The security tests are written per project and per class and perform the attack: they send `../config.py` to a file reader, a `<script>` payload to a page, or a crafted pickle to a loader, and fail while the attack succeeds. A **fake fix** is an attempt that passes the re-scan but fails the security test, that is, it fools the scanner but remains exploitable; this is measured separately.");
table("Safety-guard rules", [["#", 0.5, "c"], ["Rule", 3.6], ["Failure it prevents", 4.9]], [
  ["1", "The fix must change the code", "returning the vulnerable code unchanged"],
  ["2", "The patched file must parse", "syntax errors, truncated output"],
  ["3", "At most 30 changed lines", "rewrites that are hard to review"],
  ["4", "Same function name and parameters", "breaking callers"],
  ["5", "No new eval, exec or shell=True", "introducing a new vulnerability"],
  ["6", "No new # nosec or # nosemgrep comments", "silencing the scanner instead of fixing"],
  ["7", "Every new import must exist", "hallucinated packages"],
]);
p("If any check fails, the loop retries, up to three attempts. In v1 the retry prompt contained only the failed checks\u2019 summaries. In v2 it contains the previous fix in a `<previous_fix>` block and the first error lines that the tests printed (for example `KeyError: 'ADMIN_PASSWORD'` instead of the opaque `<test run error>`); an answer identical to a previous failed one is not re-executed but marked as a repeat; and retries use a temperature of 0.4 instead of 0.1 to encourage a different attempt.");
h3("4.1.8 User Interfaces");
p("The Streamlit review application has four tabs: *Fix* (scan a project, choose a finding, run the pipeline with live progress, inspect the verdict, the explanation, the diff, every attempt with its checks and the retrieved context, then approve or reject with a reason); *Compare models* (the same finding through several models side by side); *Results* (the evaluation tables and charts); and *Decisions* (the approval log). The Visual Studio Code extension underlines findings in the editor, offers a \u201CFix with PatchAI\u201D action and shows the proposed diff for acceptance; it communicates with a local FastAPI server that wraps the same pipeline. A command-line interface provides `doctor`, `scan` and `fix` commands.");
placeholderFigure("Insert screenshot: Streamlit review app, Fix tab, showing a verified fix with diff and checks", "The review application: verdict, diff, checks and retrieved context for one finding");
placeholderFigure("Insert screenshot: VS Code with an underlined finding and the PatchAI fix panel", "The Visual Studio Code extension");

// ---- 4.2
h2("4.2 Testing / Verification Plan");
p("The verification plan has two levels: automated tests of the system itself (Section 4.4) and an experimental evaluation of repair quality, described here.");
h3("4.2.1 Benchmark Construction");
p("The benchmark contains 63 cases. Fifty-six are generated from 14 families, two per CWE class, each in four variants with randomised names and values; these families are deliberately *different code shapes* from the training families (for example class methods, date-range queries, `%`-formatting, `make_response`, class attributes and request signatures), so that a high score indicates that the model learned to repair the class rather than memorised templates. Seven further cases are the hand-written vulnerabilities of the demonstration application, a small Flask shop with one vulnerability of each class. Each case is a small project with source code, functional tests and an exploit-based security test. Before a case is admitted it is **validated**: the scanner must detect it, its functional tests must pass, its security test must fail on the vulnerable code, and a known-correct reference fix must pass every check of the real pipeline. All 63 cases passed validation. Ten generated cases form a development split for prompt experiments; results are reported on the remaining 53 test cases.");
table("Benchmark composition (test split)", [["CWE", 1.0, "c"], ["Generated families (different from training)", 5.0], ["Cases", 1.2, "c"], ["Shop", 1.0, "c"]], [
  ["CWE-89", "repository class method; date-range query", "6", "1"],
  ["CWE-78", "command inside a class; concatenated command", "6", "1"],
  ["CWE-22", "f-string path; file write", "6", "1"],
  ["CWE-79", "%-formatted HTML; make_response", "6", "1"],
  ["CWE-798", "class attribute; credential comparison", "6", "1"],
  ["CWE-327", "request signature; key derivation", "8", "1"],
  ["CWE-502", "YAML settings; YAML file loader", "8", "1"],
  ["**Total**", "14 families \u00D7 4 variants, 10 kept for development", "**46**", "**7**"],
]);
h3("4.2.2 Metrics and Experimental Setup");
p("All models run through the **same pipeline**: the same retrieval, prompt, verification and a maximum of three attempts, at temperature 0.1 with an 8,192-token context. The compared models are the base Qwen2.5-Coder 3B, our fine-tuned PatchAI-3B and the base Qwen2.5-Coder 7B, all 4-bit quantised and served by Ollama on the RTX 4060 laptop. Table 4.6 defines the metrics. Because the test split has 53 cases, every fix rate is reported with a 95% Wilson score interval [22], which behaves well for small samples and proportions near 0 or 1:");
equation("p\u0302 \u00B1 interval:  ( p\u0302 + z\u00B2/2n \u00B1 z \u221A( p\u0302(1\u2212p\u0302)/n + z\u00B2/4n\u00B2 ) ) / ( 1 + z\u00B2/n ),   z = 1.96");
table("Evaluation metrics", [["Metric", 2.2], ["Definition", 6.8]], [
  ["Fix rate", "Share of cases whose final attempt passes the guard, the tests, the security test and the re-scan (primary metric)"],
  ["First-try fix rate", "Share of cases fixed by the first attempt, without the retry loop"],
  ["Fake-fix rate", "Share of cases with at least one attempt that passed the re-scan but failed the security test"],
  ["Guard rejection rate", "Share of attempts blocked by the safety guard"],
  ["Unreadable answers", "Share of attempts whose output was not valid JSON in the required shape"],
  ["Attempts, time", "Mean number of attempts and mean wall-clock seconds per case"],
]);
h3("4.2.3 System Test Cases");
p("Table 4.7 lists representative end-to-end test cases of the pipeline. Each is implemented as an automated test that drives the real pipeline on the demonstration project with a scripted stand-in for the model, so the expected behaviour is checked without a GPU.");
table("End-to-end test cases", [["Test", 0.6, "c"], ["Test case title", 2.1], ["Test condition", 2.5], ["System behaviour", 2.3], ["Expected result", 1.6]], [
  ["T1", "Correct fix", "reference fix for each of the 7 classes", "all checks run and pass", "verdict \u201Cfixed\u201D"],
  ["T2", "Fake fix", "weak-crypto fix that fools the scanner", "re-scan passes, attack test fails", "verdict \u201Cfailed\u201D"],
  ["T3", "Hallucinated import", "fix imports a non-existent package", "guard rule 7 blocks it", "failed, reason shown"],
  ["T4", "Hand-made escaping", "SQL fixed by replacing quotes", "re-scan still reports B608", "failed"],
  ["T5", "Retry with feedback", "wrong fix, then correct fix", "second prompt contains the error", "fixed on attempt 2"],
  ["T6", "Malformed output", "free text instead of JSON", "format check fails, retry", "fixed on attempt 2"],
  ["T7", "False alarm", "model answers false_positive", "no checks run", "verdict \u201Cfalse_positive\u201D"],
  ["T8", "Project isolation", "any fix", "checks run on a temporary copy", "project file unchanged"],
  ["T9", "Real error reaches model (v2)", "secret fix that crashes on import", "error KeyError shown in next prompt", "fixed on attempt 2"],
  ["T10", "Repeated answer (v2)", "same wrong answer three times", "attempts 2 and 3 reuse the result", "failed, marked as repeat"],
  ["T11", "Tag-wrapped answer (v2)", "correct fix inside <vulnerable_code> tags", "tags stripped before checks", "verdict \u201Cfixed\u201D"],
]);

// ---- 4.3
h2("4.3 Result Analysis");
p("This section reports the v1 experiment (RQ1), analyses the failures (RQ2) and describes the second iteration (RQ3). All v1 numbers are computed from the recorded model answers re-checked with the corrected parser (Section 4.3.6); they are therefore the fair values, and they differ from the first, uncorrected scoring only for the base models.");
h3("4.3.1 Overall Results (RQ1)");
table("Main results on the 53 test cases (v1, fair scoring)", [["Model", 2.4], ["Fix rate", 1.3, "c"], ["95% interval", 1.5, "c"], ["First try", 1.0, "c"], ["Fake fixes", 1.0, "c"], ["Guard blocks", 1.0, "c"], ["Attempts", 0.9, "c"], ["Time", 0.8, "c"]], [
  ["Qwen2.5-Coder 3B (base)", "41.5% (22)", "29.3\u201354.9%", "30.2%", "30.2%", "10.7%", "2.30", "9.5 s"],
  ["**PatchAI-3B v1 (ours)**", "**79.2% (42)**", "66.5\u201388.0%", "77.4%", "15.1%", "3.9%", "1.43", "**6.7 s**"],
  ["Qwen2.5-Coder 7B (base)", "92.5% (49)", "82.1\u201397.0%", "92.5%", "3.8%", "8.2%", "1.15", "15.4 s"],
], { highlightRows: [1] });
figure(path.join(FIG, "fix_rate.png"), "Verified fix rate per model with 95% Wilson intervals (53 test cases)", 5.2);
p("Fine-tuning almost doubled the verified fix rate of the 3B model, from 41.5% to 79.2%. The two 95% intervals do not overlap (29.3\u201354.9% versus 66.5\u201388.0%), so the improvement is not attributable to sampling variation in the benchmark. The fine-tuned model also produced schema-valid JSON in 100% of attempts, solved 77.4% of cases at the first attempt (base 3B: 30.2%), halved the fake-fix rate, and needed 1.43 attempts per case instead of 2.30, which made it 30% faster per case than its base model and 2.3\u00D7 faster than the 7B model.");
p("The 7B base model, 2.3 times larger, achieved the highest fix rate, 92.5%. The point estimates differ by 13 percentage points but the intervals overlap (66.5\u201388.0% versus 82.1\u201397.0%), so with 53 cases the gap is suggestive rather than conclusive. The answer to RQ1 is therefore that task-specific fine-tuning yields a large, significant improvement for the small model, but does not, in v1, close the gap to a model of more than twice its size.");
h3("4.3.2 Results per Vulnerability Class");
figure(path.join(FIG, "by_cwe.png"), "Fix rate per vulnerability class and model (v1, fair scoring)", 6.2);
p("Figure 4.8 shows a clear pattern. The fine-tuned model reached 100% on SQL injection, command injection, XSS and unsafe deserialisation and 86% on path traversal, exceeding or matching the 7B model on five of the seven classes, including XSS (100% versus 86%) and SQL injection (100% versus 86%). Its deficit is concentrated in two classes: **hard-coded secrets (0%)**, where even the base 3B model reached 43%, and **weak cryptography (56%)**, where every key-derivation case failed. A 0% score in a class where the base model succeeds points to something the fine-tuning taught rather than something it failed to teach, which Section 4.3.5 confirms.");
h3("4.3.3 Hand-Written Cases");
p("The seven hand-written vulnerabilities of the demonstration application were never used for training and are written in a different style from both the training and the generated benchmark families, which makes them a useful check against template effects. On these cases the fine-tuned model performed best (Table 4.9).");
table("Results on the hand-written demonstration cases", [["Case", 2.6], ["Base 3B", 1.6, "c"], ["PatchAI-3B v1", 1.6, "c"], ["Base 7B", 1.6, "c"]], [
  ["CWE-89 SQL injection (product search)", "failed", "fixed (1)", "failed"],
  ["CWE-78 command injection (ping tool)", "failed", "fixed (1)", "fixed (1)"],
  ["CWE-22 path traversal (invoice reader)", "failed", "fixed (1)", "fixed (1)"],
  ["CWE-79 XSS (search page)", "failed", "fixed (1)", "failed"],
  ["CWE-798 hard-coded admin password", "failed", "failed", "fixed (1)"],
  ["CWE-327 weak hashing", "failed", "fixed (1)", "fixed (1)"],
  ["CWE-502 unsafe deserialisation", "fixed (1)", "fixed (1)", "fixed (1)"],
  ["**Total**", "**1/7**", "**6/7**", "**5/7**"],
]);
h3("4.3.4 Retries and Failure Modes");
p("Figure 4.9 separates fixes found at the first attempt from those found by retries. Retries helped the base 3B model most (+11 percentage points), but for the fine-tuned model they added only 2 points and for the 7B none. The logs explain why: in 6 of the 12 cases in which the fine-tuned model retried, all of its attempts were **identical**; the corresponding figures were 16 of 37 for the base 3B model and 12 of 14 for the 7B (Table 4.10). With the v1 retry prompt, which stated only that tests had failed and did not show the previous fix, the models frequently had nothing to act on.");
figure(path.join(FIG, "attempts.png"), "Fixes at the first attempt and after retries", 5.6);
table("Retry behaviour (v1)", [["Model", 3.0], ["Cases with retries", 2.0, "c"], ["All attempts identical", 2.2, "c"], ["Gain from retries", 1.8, "c"]], [
  ["Qwen2.5-Coder 3B (base)", "37", "16 (43%)", "+11.3 pp"],
  ["PatchAI-3B v1 (ours)", "12", "6 (50%)", "+1.9 pp"],
  ["Qwen2.5-Coder 7B (base)", "14", "12 (86%)", "0"],
]);
p("Figure 4.10 shows which check rejected the last attempt of each unfixed case. For all models the dominant reason is broken project tests, which means that the patch changed the program\u2019s behaviour or crashed it; this is precisely the failure that scanner-only evaluation would not detect.");
figure(path.join(FIG, "failures.png"), "Reason for failure of the unfixed test cases (last attempt)", 5.6);
h3("4.3.5 Error Analysis (RQ2)");
p("We read the complete record of every attempt (prompt context, model answer, diff and check output) for all unfixed cases. Table 4.11 summarises the root causes. Two of them are properties of the fine-tuned model that were learned from the training data, which is the central finding of RQ2: **fine-tuning gives a small model strong habits, and where a habit does not fit the code, the model fails consistently.**");
table("Root causes found in the v1 logs", [["Observation", 2.6], ["Evidence in the logs", 3.4], ["Root cause", 3.0]], [
  ["Fine-tuned model: 0% on hard-coded secrets", "every attempt wrote os.environ[\"NAME\"]; tests failed with KeyError at import", "two thirds of the secret fixes in the training data used os.environ[...], which raises when the variable is unset"],
  ["Fine-tuned model: 0/4 key-derivation cases", "returned .hex() strings or used a random salt; tests expect stable bytes", "training contained password hashing only (random salt, hex string); the habit was applied to key derivation"],
  ["Credential comparison left in the code", "replaced == with hmac.compare_digest but kept the literal", "no training family showed a credential check"],
  ["Retries repeated the same answer", "identical diffs in 6 of 12 retried cases", "retry prompt lacked the previous fix and the concrete error"],
  ["Imbalanced training data", "25.7% false alarms, 72 command-injection examples", "sampling defect in the generator"],
  ["Base 7B under-scored", "correct fixes wrapped in <vulnerable_code> tags counted as syntax errors", "parser did not strip echoed prompt tags (measurement artefact)"],
]);
h3("4.3.6 Measurement Validity: Correcting the Scoring");
p("The last row of Table 4.11 concerns the measurement, not a model. The base models, especially the 7B, sometimes echoed the `<vulnerable_code>` tags from the prompt around otherwise correct code; the original parser did not remove them, the safety guard rejected the result as a syntax error, and the 7B lost 11 cases in this way, including all of its XSS cases. Because every model answer had been recorded, we corrected the parser and **re-scored the recorded answers** without running any model (`eval/rescore.py`). The re-scoring is exact whenever the first answer passes, which covers every changed verdict. Figure 4.11 shows the effect: the 7B rose from 73.6% to 92.5%, while the fine-tuned model, which had learned the output format and never echoed tags, was unaffected. Reporting the uncorrected numbers would have overstated the fine-tuned model\u2019s advantage; all results in this report use the corrected scoring, and both versions are kept in the repository.");
figure(path.join(FIG, "rescoring.png"), "Effect of the corrected parser on the v1 fix rates", 5.4);
h3("4.3.7 Second Iteration (RQ3)");
p("Each root cause was addressed by a specific change (Table 4.12). The changes are general rather than tailored to the failing test cases: for example, the new training families teach credential checks and key stretching with code shapes that differ from the benchmark\u2019s, and the retry improvements apply to every class. We note openly that two training families were added after examining test failures; their code differs from the benchmark families, but the concepts overlap, and this should be considered when interpreting v2 results on CWE-798 and CWE-327.");
table("Changes in the second iteration (v2)", [["Root cause", 2.8], ["v2 change", 4.4], ["Expected effect", 1.8]], [
  ["Unfair parsing", "strip echoed prompt tags and fences before checks; re-score v1", "fair comparison"],
  ["Opaque errors", "checks report the first error lines printed by the tests", "actionable feedback"],
  ["Repeated retries", "retry prompt shows the previous fix and the error; repeats detected; retry temperature 0.4", "retries change the answer"],
  ["Crashing secret fixes", "all secret fixes use os.environ.get(NAME, \"\"); credential-check family", "CWE-798 recovers"],
  ["Key-derivation habit", "key-stretching family (PBKDF2, deterministic, bytes); checksums keep return type", "CWE-327 recovers"],
  ["Generator defect", "fixed per-class quotas; exactly 8% false alarms; more variants", "balanced data"],
  ["Synthetic data only", "21 real CVE fixes from CVEfixes (Section 4.1.5)", "real-world code"],
  ["Training never sees feedback use", "20% retry examples with a typical mistake and its exact error", "learns to use feedback"],
]);
p("The v2 model was trained (2,289 training and 252 validation examples, 117 minutes, final validation loss 0.0303 against 0.0342 for v1; Figure 4.12) and evaluated by a single automated script on the GPU laptop on 9 November 2026. The script kept the v1 model, so the final comparison includes four models on the same 53 test cases in one run (run `v2`): the base 3B, PatchAI-3B v1, PatchAI-3B v2 and the base 7B. Because v1 and v2 were measured on the same day with the same pipeline, the comparison between them is not affected by run-to-run variation.");
figure(path.join(FIG, "loss_v1_v2.png"), "Training and validation loss of v1 and v2 (log scale)", 5.4);
table("Results of the second iteration (run v2, 53 test cases)", [["Model", 2.6], ["Fix rate", 1.4, "c"], ["95% interval", 1.6, "c"], ["CWE-798", 1.1, "c"], ["CWE-327", 1.1, "c"], ["Shop", 0.9, "c"]], [
  ["Qwen2.5-Coder 3B (base)", "49.1% (26)", "36.1–62.1%", "57%", "44%", "4/7"],
  ["PatchAI-3B v1", "71.7% (38)", "58.4–82.0%", "0%", "56%", "6/7"],
  ["**PatchAI-3B v2 (ours)**", "**86.8% (46)**", "75.2–93.5%", "**57%**", "**100%**", "6/7"],
  ["Qwen2.5-Coder 7B (base)", "90.6% (48)", "79.7–95.9%", "71%", "100%", "5/7"],
], { highlightRows: [2] });
figure(path.join(FIG, "fix_rate_v2.png"), "Verified fix rate of the four models in run v2, with 95% Wilson intervals", 6.0);
p("The second iteration raised the fine-tuned model from 71.7% to **86.8%**, 15 percentage points in the same run. The two classes targeted by the error analysis recovered as intended: hard-coded secrets rose from 0% to 57% and weak cryptography from 56% to 100% (Figure 4.14). Command injection, where v1 had only 72 training examples, rose from 71% to 100%. Two classes fell by one case each (path traversal and XSS, −14 points); with seven cases per class, a single case is 14 points, so these changes are within noise. v2 was also the cleanest model in the run: no attempt was blocked by the safety guard (v1: 3.6%, base 7B: 14.3%), and its fake-fix rate halved again, from 13.2% to 5.7%.");
figure(path.join(FIG, "v1_to_v2.png"), "Fix rate per vulnerability class, v1 against v2 (run v2)", 5.6);
p("Against the 7B base model, v2 reached 86.8% versus 90.6% while taking 6.2 seconds per case instead of 20.1 (Figure 4.15). The 95% intervals overlap almost completely (75.2–93.5% versus 79.7–95.9%), so the two models are statistically indistinguishable on this benchmark, and v2 is about three times faster with a model less than half the size. On the hand-written demonstration cases v2 solved 6 of 7, one more than the 7B. The answer to RQ3 is therefore that targeted changes derived from the error analysis closed most of the gap to the 7B model without changing the model size.");
figure(path.join(FIG, "speed_accuracy_v2.png"), "Accuracy against speed in run v2", 5.4);
p("Three observations temper this result. First, **retries rescued no cases for v1, v2 or the 7B** in run v2 (first-try rate equals fix rate); only the base 3B gained from them. The retry improvements made the feedback more informative, but a model that fails once on a case tends to fail again. Second, **the same v1 model scored 79.2% in the re-scored v1 run and 71.7% in run v2**: run-to-run variation of about seven points means that models should only be compared within one run, as done here. Third, **v2's seven failures are concentrated in two patterns** (Figure 4.16): in all three path-traversal cases with an f-string path, the project tests and the attack test passed and only our own Semgrep rule still reported the code, which suggests that the rule does not recognise a sanitiser applied before the path is built, so these may be correct fixes rejected by the scanner; and in the three credential-comparison secret cases, an attempt removed the literal in a way that broke the project tests. The scoring rule was not changed after seeing these results.");
figure(path.join(FIG, "failures_v2.png"), "Reason for failure of the unfixed test cases in run v2 (last attempt)", 5.6);
h3("4.3.8 Threats to Validity");
bullets([
  "**Benchmark size.** With 53 test cases, differences of a few percentage points are within sampling error; we therefore report confidence intervals and avoid claims the intervals do not support.",
  "**Template-generated cases.** Most benchmark cases are generated from templates. We mitigate this by using code shapes that differ from the training data and by reporting the hand-written cases separately.",
  "**Security tests as oracle.** An attack test shows that the attacks we wrote fail, not that every possible attack fails.",
  "**Data-informed changes.** Two v2 training families were designed after reading v1\u2019s failures (Section 4.3.7).",
  "**Run-to-run variation.** Each model was evaluated at temperature 0.1, and the same v1 model scored 79.2% in one run and 71.7% in another. All model comparisons in Section 4.3.7 are therefore made within a single run.",
  "**Scanner as part of the oracle.** In three v2 path-traversal failures only our own Semgrep rule rejected the fix; the rule may be stricter than necessary, which would understate v2.",
  "**Real-world data volume.** Only 21 real CVE fixes survived filtering, so the training data remains predominantly synthetic.",
]);

// ---- 4.4
h2("4.4 Quality Assurance");
p("Quality assurance focused on making both the system and the measurements trustworthy.");
bullets([
  "**Automated test suite.** 93 automated tests (pytest) cover the units (parsing, patching, guard rules, prompts, metrics and the Wilson interval), retrieval and review, the local server and its background fix jobs, every page of the review app (headless), the training-data generator and the CVEfixes reconstruction, and the end-to-end pipeline on the demonstration project (Table 4.7). They use a scripted stand-in for the model and need neither a GPU nor Ollama, so every team member can run them; the GPU run executes them before training.",
  "**Validated benchmark.** Every benchmark case is admitted only if it is detectable, exploitable and solvable by a reference fix through the real pipeline (Section 4.2.1).",
  "**Reproducibility.** Each training run stores its settings, the SHA-256 hashes of the training and validation files and the dataset statistics; each evaluation run stores the models, the configuration, the prompt version and the code commit; the complete record of every attempt is kept for analysis. Data generation is seeded.",
  "**Honest measurement.** Results are reported with confidence intervals, the hand-written cases are reported separately, and the scoring correction of Section 4.3.6 is documented with both versions of the numbers retained.",
  "**Single-command execution.** The GPU-side work (checks, tests, data, training, export, evaluation and report) is a single resumable script, which removes manual steps as a source of error.",
]);

// ================================================================ CHAPTER 5
chapter("Standards Adopted");
h2("5.1 Design Standards");
p("The requirements in Section 3.2 follow the structure recommended by ISO/IEC/IEEE 29148 for requirements engineering (the successor of IEEE 830 [28]): uniquely identified, verifiable functional and non-functional requirements, each traced to the module that realises it. The design description in Section 3.3 follows the viewpoints of IEEE 1016 (context, composition, interfaces and data flow). Security content follows the MITRE CWE taxonomy [1] for classification and the OWASP Top 10 [2] for prioritisation, and the security guides in the knowledge base follow the corresponding OWASP prevention guidance. The architecture applies established secure-design principles: least privilege (the model may rewrite only one function), defence in depth (four independent checks), fail-safe defaults (nothing is applied without approval), and isolation (execution only on a temporary copy).");
h2("5.2 Coding Standards");
p("The Python code follows PEP 8 [31] for layout and naming and uses type hints (PEP 484) throughout. Data passed between pipeline stages is defined as validated Pydantic models (Finding, CodeContext, FixProposal, Attempt, FixResult), so malformed data fails at the boundary rather than deep inside the pipeline. Further conventions:");
bullets([
  "One module per pipeline step, each with a docstring explaining its role; no module longer than necessary.",
  "Functions perform a single task; the pipeline entry point converts every error into a reported verdict.",
  "All settings in one configuration file (`config.yaml`) instead of constants scattered in code.",
  "Only one module (`llm.py`) talks to a model, which makes the system testable with a scripted model.",
  "Files are read and written byte-exactly so that Windows line endings in user projects are preserved.",
]);
h2("5.3 Testing Standards");
p("Testing follows the concepts of ISO/IEC/IEEE 29119 [28]: test levels (unit, integration and system tests), documented test cases with conditions and expected results (Table 4.7), and regression testing on every change. Repair quality is evaluated with an execution-based oracle rather than textual similarity, and statistical results are reported with 95% Wilson intervals [22]. Quality characteristics such as functional suitability, security and maintainability are considered in the sense of ISO/IEC 25010.");
h2("5.4 Cost Analysis");
p("PatchAI was built entirely with open-source software and existing hardware, so its direct cost is limited to electricity (Table 5.1). One licensing point matters for deployment: the Qwen2.5-Coder-3B checkpoint is distributed under the Qwen Research License, which permits academic use but not commercial use, whereas the 7B model is Apache-2.0 licensed. A commercial deployment would therefore require a different 3B base model or a separate licence.");
table("Cost analysis", [["Item", 2.6], ["Used in this project", 4.0], ["Cost", 2.4]], [
  ["Training hardware", "existing RTX 4060 laptop of a team member", "no additional cost"],
  ["Software and models", "open-source (Bandit, Semgrep CE, Ollama, Unsloth, TRL, PEFT, fastembed, Streamlit); Qwen2.5-Coder", "no licence fees (academic use)"],
  ["Data", "synthetic data; CVEfixes (Apache-2.0)", "no cost"],
  ["Training energy", "115.5 min at roughly 150 W", "\u2248 0.3 kWh"],
  ["Evaluation energy", "159 model runs plus checks", "< 0.5 kWh"],
  ["Inference per fix", "local, seconds on GPU, minutes on CPU", "no per-request fee"],
  ["Hosted-API alternative", "per-token charges and source code sent to a third party", "recurring; privacy constraint"],
]);

// ================================================================ CHAPTER 6
chapter("Conclusion and Future Scope");
h2("6.1 Conclusion");
p("This project developed PatchAI, a local system that detects seven classes of security vulnerabilities in Python, proposes fixes with a fine-tuned small language model grounded by hybrid retrieval, and accepts a fix only when it is verified by a safety guard, the project\u2019s tests, an exploit-based security test and a re-scan, with a human making the final decision. The system runs end to end on ordinary laptops, keeps source code on the developer\u2019s machine, and explains each proposal through its diff, its checks and the material the model read.");
p("Regarding **RQ1**, QLoRA fine-tuning of Qwen2.5-Coder-3B on about 2,500 pipeline-identical examples raised its verified fix rate from 41.5% to 79.2%, a statistically clear improvement, together with fully valid output, fewer fake fixes and lower latency; the fine-tuned model performed best on the hand-written cases, while the 2.3\u00D7 larger 7B model remained ahead overall at 92.5%. Regarding **RQ2**, the remaining failures were concentrated in two classes and traced to habits learned from the training data, and retries were largely ineffective because the feedback did not show the model what to change. The analysis also exposed a scoring artefact that, uncorrected, would have overstated our model\u2019s advantage, which underlines the value of recording and re-checking every attempt. Regarding **RQ3**, each finding was turned into a specific change to the data, the prompt, the feedback or the scoring. Measured in one run alongside v1 and both base models, the second iteration raised the fine-tuned model from 71.7% to 86.8%, recovered the two weak classes (hard-coded secrets 0% → 57%, weak cryptography 56% → 100%), eliminated safety-guard rejections, and brought the 3B model within the confidence interval of the 7B model (90.6%) at about a third of its time per case. Retries still rescued no cases for the stronger models, and the remaining failures point to a scanner rule that may reject correct path-traversal fixes; both are natural next steps.");
p("Beyond the numbers, the project shows that the reliability of AI-assisted security repair depends at least as much on the surrounding engineering, namely exploit-based verification, faithful training data and honest measurement, as on the size of the model.");
h2("6.2 Future Scope");
bullets([
  "**Broader coverage:** more CWE classes (for example server-side request forgery and XML external entities) and other languages such as JavaScript and Java.",
  "**More real-world data:** larger collections of real fixes, for example by relaxing the single-function constraint or using additional vulnerability-fix datasets.",
  "**Multi-location repairs:** fixes that span several functions or files, with a correspondingly richer review interface.",
  "**Stronger isolation:** running tests inside a container or virtual machine so that untrusted projects can be processed safely.",
  "**Preference optimisation and larger bases:** completing the DPO stage, and fine-tuning the 7B model, which may combine the 7B\u2019s strength with our model\u2019s format reliability.",
  "**Automatic exploit-test generation:** generating security tests for projects that have none, which is currently the main manual effort.",
  "**Developer workflow integration:** running PatchAI in continuous integration to propose verified fixes as pull requests, and a user study of how reviewers use the explanations.",
]);

// ================================================================ REFERENCES
unnumberedChapter("References");
const refs = [
  "MITRE Corporation, \u201CCommon Weakness Enumeration (CWE),\u201D https://cwe.mitre.org, accessed Nov. 2026.",
  "OWASP Foundation, \u201COWASP Top 10:2021,\u201D https://owasp.org/Top10/, 2021.",
  "C. Le Goues, T. Nguyen, S. Forrest, and W. Weimer, \u201CGenProg: A Generic Method for Automatic Software Repair,\u201D IEEE Transactions on Software Engineering, vol. 38, no. 1, pp. 54\u201372, 2012.",
  "M. Monperrus, \u201CAutomatic Software Repair: A Bibliography,\u201D ACM Computing Surveys, vol. 51, no. 1, 2018.",
  "Z. Chen, S. Kommrusch, and M. Monperrus, \u201CNeural Transfer Learning for Repairing Security Vulnerabilities in C Code,\u201D IEEE Transactions on Software Engineering, vol. 49, no. 1, pp. 147\u2013165, 2023.",
  "M. Fu, C. Tantithamthavorn, T. Le, V. Nguyen, and D. Phung, \u201CVulRepair: A T5-Based Automated Software Vulnerability Repair,\u201D in Proc. ESEC/FSE, 2022, pp. 935\u2013947.",
  "H. Pearce, B. Ahmad, B. Tan, B. Dolan-Gavitt, and R. Karri, \u201CAsleep at the Keyboard? Assessing the Security of GitHub Copilot\u2019s Code Contributions,\u201D in Proc. IEEE Symposium on Security and Privacy, 2022, pp. 754\u2013768.",
  "H. Pearce, B. Tan, B. Ahmad, R. Karri, and B. Dolan-Gavitt, \u201CExamining Zero-Shot Vulnerability Repair with Large Language Models,\u201D in Proc. IEEE Symposium on Security and Privacy, 2023, pp. 2339\u20132356.",
  "G. Bhandari, A. Naseer, and L. Moonen, \u201CCVEfixes: Automated Collection of Vulnerabilities and Their Fixes from Open-Source Software,\u201D in Proc. PROMISE, 2021, pp. 30\u201339.",
  "B. Hui et al., \u201CQwen2.5-Coder Technical Report,\u201D arXiv:2409.12186, 2024.",
  "E. J. Hu et al., \u201CLoRA: Low-Rank Adaptation of Large Language Models,\u201D in Proc. ICLR, 2022.",
  "T. Dettmers, A. Pagnoni, A. Holtzman, and L. Zettlemoyer, \u201CQLoRA: Efficient Finetuning of Quantized LLMs,\u201D in Proc. NeurIPS, 2023.",
  "R. Rafailov, A. Sharma, E. Mitchell, S. Ermon, C. D. Manning, and C. Finn, \u201CDirect Preference Optimization: Your Language Model Is Secretly a Reward Model,\u201D in Proc. NeurIPS, 2023.",
  "P. Lewis et al., \u201CRetrieval-Augmented Generation for Knowledge-Intensive NLP Tasks,\u201D in Proc. NeurIPS, 2020.",
  "S. Robertson and H. Zaragoza, \u201CThe Probabilistic Relevance Framework: BM25 and Beyond,\u201D Foundations and Trends in Information Retrieval, vol. 3, no. 4, pp. 333\u2013389, 2009.",
  "G. V. Cormack, C. L. A. Clarke, and S. B\u00FCttcher, \u201CReciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods,\u201D in Proc. ACM SIGIR, 2009, pp. 758\u2013759.",
  "R. Nogueira and K. Cho, \u201CPassage Re-ranking with BERT,\u201D arXiv:1901.04085, 2019.",
  "S. Xiao, Z. Liu, P. Zhang, and N. Muennighoff, \u201CC-Pack: Packaged Resources to Advance General Chinese Embedding,\u201D arXiv:2309.07597, 2023.",
  "X. Chen, M. Lin, N. Sch\u00E4rli, and D. Zhou, \u201CTeaching Large Language Models to Self-Debug,\u201D in Proc. ICLR, 2024.",
  "N. Shinn, F. Cassano, A. Gopinath, K. Narasimhan, and S. Yao, \u201CReflexion: Language Agents with Verbal Reinforcement Learning,\u201D in Proc. NeurIPS, 2023.",
  "C. S. Xia and L. Zhang, \u201CKeep the Conversation Going: Fixing 162 out of 337 Bugs for $0.42 Each Using ChatGPT,\u201D in Proc. ISSTA, 2024.",
  "E. B. Wilson, \u201CProbable Inference, the Law of Succession, and Statistical Inference,\u201D Journal of the American Statistical Association, vol. 22, no. 158, pp. 209\u2013212, 1927.",
  "PyCQA, \u201CBandit: A Tool Designed to Find Common Security Issues in Python Code,\u201D https://github.com/PyCQA/bandit.",
  "Semgrep, Inc., \u201CSemgrep: Lightweight Static Analysis for Many Languages,\u201D https://semgrep.dev.",
  "Ollama, \u201CGet Up and Running with Large Language Models Locally,\u201D https://ollama.com.",
  "L. von Werra et al., \u201CTRL: Transformer Reinforcement Learning,\u201D https://github.com/huggingface/trl; S. Mangrulkar et al., \u201CPEFT: Parameter-Efficient Fine-Tuning Methods,\u201D https://github.com/huggingface/peft; Unsloth, https://github.com/unslothai/unsloth.",
  "G. Gerganov et al., \u201Cllama.cpp and the GGUF Format,\u201D https://github.com/ggml-org/llama.cpp.",
  "ISO/IEC/IEEE 29148:2018, Requirements Engineering; IEEE 1016-2009, Software Design Descriptions; ISO/IEC/IEEE 29119, Software Testing; ISO/IEC 25010:2011, System and Software Quality Models.",
  "C. E. Jimenez et al., \u201CSWE-bench: Can Language Models Resolve Real-World GitHub Issues?\u201D in Proc. ICLR, 2024.",
  "T. Nguyen et al., \u201CMS MARCO: A Human Generated MAchine Reading COmprehension Dataset,\u201D arXiv:1611.09268, 2016.",
  "G. van Rossum, B. Warsaw, and N. Coghlan, \u201CPEP 8 \u2013 Style Guide for Python Code,\u201D https://peps.python.org/pep-0008/, 2001.",
];
refs.forEach((r, i) => add(new Paragraph({
  spacing: { after: 100, line: 276 }, indent: { left: 560, hanging: 560 }, alignment: AlignmentType.LEFT,
  children: [new TextRun({ text: `[${i + 1}]\t`, size: 22 }), ...runs(r, { size: 22 })],
  tabStops: [{ type: "left", position: 560 }],
})));

// ================================================================ INDIVIDUAL CONTRIBUTION
const roles = [
  ["Training", "designed and ran the fine-tuning: the synthetic training-data generator, the dataset builder, QLoRA supervised fine-tuning on the RTX 4060, GGUF export to Ollama and the optional DPO stage; analysed the loss curves and the training-data statistics.", "Chapter 4.1.5\u20134.1.6 (training data, fine-tuning)"],
  ["Retrieval (RAG)", "built the knowledge base (security guides, past fixes), the hybrid retrieval (BGE embeddings, BM25, reciprocal rank fusion, cross-encoder re-ranking) and the call-graph-aware code retrieval.", "Chapter 2.6, 3.3.2 (retrieval design), 4.1.3"],
  ["Model and fixing", "designed the prompt and the JSON output contract, the model client, the attempt-and-retry loop with execution feedback and the patch splicing.", "Chapter 2.4\u20132.5, 4.1.4, 4.1.7 (feedback loop)"],
  ["Detection and checks", "implemented the scanners and the custom Semgrep taint rules, context extraction, the safety guard, the test/exploit/re-scan checks and the demonstration application with its security tests.", "Chapter 2.1\u20132.2, 4.1.1\u20134.1.2, 4.1.7 (verification)"],
  ["Interfaces and evaluation", "built the Streamlit review application, the VS Code extension and local server, the benchmark, the evaluation runner, the metrics and the result analysis.", "Chapter 4.1.8, 4.2, 4.3"],
];
members.forEach((m, i) => {
  pageBreak();
  add(new Paragraph({ heading: i === 0 ? HeadingLevel.HEADING_1 : undefined, alignment: AlignmentType.LEFT, spacing: { after: 240 },
    children: [new TextRun({ text: i === 0 ? "Individual Contribution" : "INDIVIDUAL CONTRIBUTION REPORT", bold: true, size: i === 0 ? 44 : 28 })] }));
  if (i === 0) add(new Paragraph({ spacing: { after: 240 }, children: [new TextRun({ text: "INDIVIDUAL CONTRIBUTION REPORT", bold: true, size: 28 })] }));
  add(new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: PROJECT.toUpperCase(), bold: true, size: 28 })] }));
  add(new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: m, size: 24, highlight: "yellow" })] }));
  add(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 240 }, children: [new TextRun({ text: rolls[i], size: 24, highlight: "yellow" })] }));
  const para = (label, text) => add(new Paragraph({ alignment: AlignmentType.JUSTIFIED, spacing: { line: 300, after: 160 },
    children: [new TextRun({ text: `${label}: `, bold: true, size: 24 }), ...runs(text, { size: 24 })] }));
  para("Abstract", "PatchAI is a local system that repairs seven classes of security vulnerabilities in Python code. It combines static detection, hybrid retrieval-augmented generation, a Qwen2.5-Coder-3B model fine-tuned with QLoRA, and verification of every fix by tests, an exploit-based security test and a re-scan, with human approval. Fine-tuning raised the verified fix rate of the 3B model from 41.5% to 79.2% on a validated benchmark, and a second, error-analysis-driven iteration reached 86.8%, close to a 7B model (90.6%) at a third of the time per case.");
  para("Individual contribution and findings", `As the owner of the **${roles[i][0]}** area, I ${roles[i][1]} [[Edit: describe your own work and findings in your words, within the word limit.]]`);
  para("Individual contribution to project report preparation", `${roles[i][2]}. [[Edit to match the sections you wrote.]]`);
  para("Individual contribution for project presentation and demonstration", "[[Describe your part of the presentation and of the live demonstration.]]");
  add(new Paragraph({ spacing: { before: 600 }, children: [new TextRun({ text: "Full Signature of Supervisor:", size: 24 }), new TextRun({ text: "\tFull signature of the student:", size: 24 })], tabStops: [{ type: "left", position: 5000 }] }));
  add(new Paragraph({ spacing: { before: 400 }, children: [new TextRun({ text: "\u2026\u2026\u2026\u2026\u2026\u2026\u2026\u2026\u2026\u2026\t\u2026\u2026\u2026\u2026\u2026\u2026\u2026\u2026\u2026\u2026", size: 24 })], tabStops: [{ type: "left", position: 5000 }] }));
});

// ================================================================ PLAGIARISM
unnumberedChapter("Plagiarism Report");
add(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 400 }, children: [new TextRun({ text: "TURNITIN PLAGIARISM REPORT", size: 32 })] }));
add(new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "(This report is mandatory for all the projects and plagiarism must be below 25%)", size: 26, bold: true })] }));
placeholderFigure("Insert the Turnitin originality report here", null);

// ================================================================ DOCUMENT
const headingRun = (size) => ({ run: { font: FONT, size, bold: true, color: "000000" } });
const doc = new Document({
  creator: "PatchAI team",
  title: PROJECT,
  description: "Project report, KIIT Deemed to be University",
  features: { updateFields: true },
  styles: {
    default: { document: { run: { font: FONT, size: 24 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, ...headingRun(44),
        paragraph: { spacing: { before: 240, after: 360 }, keepNext: true, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, ...headingRun(30),
        paragraph: { spacing: { before: 300, after: 140 }, keepNext: true, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, ...headingRun(26),
        paragraph: { spacing: { before: 220, after: 100 }, keepNext: true, outlineLevel: 2 } },
      { id: "FigureCaption", name: "Figure Caption", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 21, italics: false }, paragraph: { alignment: AlignmentType.CENTER, spacing: { before: 60, after: 240 } } },
      { id: "TableCaption", name: "Table Caption", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 21, bold: true }, paragraph: { alignment: AlignmentType.CENTER, spacing: { before: 200, after: 100 } } },
    ],
  },
  numbering: { config: [
    { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
  ] },
  sections: [
    {
      properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440, header: 708, footer: 708 },
        pageNumbers: { start: 1, formatType: NumberFormat.LOWER_ROMAN } }, titlePage: true },
      footers: {
        default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: [PageNumber.CURRENT], size: 22 })] })] }),
        first: new Footer({ children: [new Paragraph({ children: [] })] }),
      },
      children: front,
    },
    {
      properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440, header: 708, footer: 708 },
        pageNumbers: { start: 1, formatType: NumberFormat.DECIMAL } } },
      headers: { default: new Header({ children: [new Paragraph({
        alignment: AlignmentType.RIGHT, border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "8C8C8C", space: 4 } },
        children: [new TextRun({ text: `${SHORT}: Verified AI-Assisted Secure Code Repair`, italics: true, size: 20 })] })] }) },
      footers: { default: new Footer({ children: [new Paragraph({
        border: { top: { style: BorderStyle.SINGLE, size: 4, color: "8C8C8C", space: 4 } },
        children: [new TextRun({ text: "School of Computer Science and Engineering, KIIT, BBSR", size: 20 }),
          new TextRun({ children: [new PositionalTab({ alignment: PositionalTabAlignment.RIGHT, relativeTo: PositionalTabRelativeTo.MARGIN, leader: PositionalTabLeader.NONE }), PageNumber.CURRENT], size: 20 })] })] }) },
      children: body,
    },
  ],
});

Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(OUT, buf); console.log("wrote", OUT, buf.length); });
