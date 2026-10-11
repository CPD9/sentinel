// One plain-language definition per term an officer meets. Every ⓘ in the app reads from here, so explanations stay identical.
// Wording follows what the pipeline actually does (pipeline/rules.py, confidence.py, decide.py; CLAUDE.md steps 6-8).
export const GLOSSARY = {
  alarm: {
    title: "Alert",
    text: "A check found a verified passage that breaks a rule, the risk is at or above the alert line and nothing makes the system unsure. Without a verified supporting passage there is never an alert, whatever the lines.",
  },
  review: {
    title: "Review",
    text: "The system is not sure enough to decide alone, so a person decides. Reasons: a processing step failed, evidence could not be verified or points both ways, confidence is below the gate, or the risk sits between the review line and the alert line. Review is not an alert.",
  },
  no_alert: {
    title: "No alert",
    text: "No check found a rule-breaking passage with enough risk. The call may still contain keywords; they alone never raise an alert.",
  },
  calls_checked: {
    title: "Calls checked",
    text: "Every call that has finished processing. Sentinel checks each call completely, not a sample.",
  },
  processing: {
    title: "Processing",
    text: "Calls still being transcribed and checked. They get a decision automatically when they finish.",
  },
  risk: {
    title: "Risk",
    text: "How strongly the call matches a kind of fraud, from 0 to 100 %. It is the highest score of all checks; each check scores the facts the AI found in the call, plus a small boost when a keyword appears in the same passage.",
  },
  confidence: {
    title: "Confidence",
    text: "How much the system trusts its own decision, from 0 to 100 %. It combines five signals: how clear the transcript is on the cited passages, how far the risk is from a threshold, contradicting facts, evidence that could not be verified, and audio quality.",
  },
  confidence_gate: {
    title: "Confidence gate",
    text: "If confidence is below this value on a call with some risk, the system does not decide alone: the call goes to review.",
  },
  alarm_threshold: {
    title: "Alert line",
    text: "The risk at which a call becomes an alert. Lower catches more fraud but gives more false alarms; higher gives fewer false alarms but misses more.",
  },
  review_threshold: {
    title: "Review line",
    text: "From this risk up to the alert line, a call is handed to a person instead of being dropped.",
  },
  finding: {
    title: "Finding",
    text: "One kind of fraud the system considered for this call, with its risk and the reason in one sentence.",
  },
  evidence: {
    title: "Evidence passage",
    text: "The exact words in the call that carry a finding, with who said them and when. Each one is checked against the transcript before it may count.",
  },
  snippet: {
    title: "Audio snippet",
    text: "The cited passage cut from the recording with 10 seconds before and after, so you hear the context without listening to the whole call.",
  },
  counter_evidence: {
    title: "Counter-evidence",
    text: "A passage that speaks against the finding, for example a refusal or a valid authorisation. It lowers the risk.",
  },
  keyword_family: {
    title: "Keyword family",
    text: "A group of words for one kind of fraud, with their Swiss German variants. A keyword only points to a passage; the decision comes from the checks.",
  },
  match_strictness: {
    title: "Match strictness",
    text: "How exactly a transcribed word must match a keyword to count. 1.00 means exact spelling only; lower values also catch dialect spellings and small transcription errors.",
  },
  check: {
    title: "Check",
    text: "One rule per kind of fraud. It looks at the facts found in the call (who said what, and whether it was a request, a disclosure or a refusal) and gives a risk.",
  },
  caught: {
    title: "Caught",
    text: "Calls that needed attention (expected alert or review) and were flagged as alert or review.",
  },
  missed: {
    title: "Missed",
    text: "Calls that needed attention but came out as no alert. These are the costly mistakes.",
  },
  false_alarm: {
    title: "False alarm",
    text: "An alert on a call that should not be one. Each one costs an officer time.",
  },
  precision: {
    title: "Precision",
    text: "Of all the calls Sentinel flagged, the share that really needed it. Low precision means many false alarms.",
  },
  recall: {
    title: "Recall",
    text: "Of all the calls that really needed attention, the share Sentinel flagged. Low recall means missed cases.",
  },
  fact: {
    title: "Fact",
    text: "Something a speaker did in the call, found by the AI over the whole conversation: who asked for, disclosed or warned about which kind of information, with the exact words quoted. Every fact is checked against the transcript; a fact whose quote cannot be found there is dropped and makes the system less sure.",
  },
  rule: {
    title: "Rule",
    text: "One fixed check per kind of fraud. It scores the verified facts (plus a small boost when a keyword appears in the same passage) and fires when the risk is high enough. Rules are configuration, not AI: the same facts always give the same result.",
  },
  ci: {
    title: "Confidence interval",
    text: "The range the true value likely lies in. With only a few test calls the range is wide, so read the range, not just the single number.",
  },
} as const;

export type Term = keyof typeof GLOSSARY;
