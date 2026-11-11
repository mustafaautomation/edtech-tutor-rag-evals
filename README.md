# edtech-tutor-rag-evals

Personal open-source demo by Muhammad Mustafa. It is a small RAG tutor for a fictional introductory statistics course, Harborlight College STAT 101, plus an evaluation gate built on [RAGAS](https://docs.ragas.io/) 0.4.3.

The lesson notes are synthetic. They were written for this repository. They are not a textbook, not student work, and not customer data. The instructor named in the notes, Dr. Lena Okonkwo, is fictional.

[![CI](https://github.com/mustafaautomation/edtech-tutor-rag-evals/actions/workflows/ci.yml/badge.svg)](https://github.com/mustafaautomation/edtech-tutor-rag-evals/actions/workflows/ci.yml)

## What it does

A student question is chunked against the lesson notes, embedded, and retrieved. A generator then answers under three rules:

- Answer only from the retrieved notes. If the notes do not contain the answer, say so.
- For a graded problem set, give the published hint and do not give the final result.
- Refuse questions that are outside the STAT 101 syllabus, including requests to ignore those rules.

Offline runs do not call a model API. They use a deterministic tutor that applies those rules in code, so CI can score the pipeline with no key. Live mode sends the same system prompt to OpenAI or Anthropic.

## Architecture

```mermaid
flowchart LR
    notes[Lesson notes] --> chunker[Section chunker]
    chunker --> embed[Hashing embedder]
    embed --> index[FAISS or pgvector]
    question[Student question] --> index
    index --> retriever[Top-k notes]
    retriever --> policy[Policy filter]
    policy --> prompt[System prompt plus notes]
    prompt --> gen[Generator]
    gen --> answer[Answer]
    gen --- det[Deterministic tutor]
    gen --- openai[OpenAI]
    gen --- anthropic[Anthropic]
```

Graded solutions are stored in the corpus and kept out of the index. The guarded path adds the hint for the named problem set. The unguarded path adds the solution instead. That is the before/after comparison below.

## Run it

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-groups
uv run harborlight-eval --mode offline --variant improved
uv run harborlight-ask "What is the arithmetic mean of a sample?"
```

`harborlight-eval` prints one line per metric and exits 0 only when every gated metric is at or above `config/thresholds.yaml`. The improved variant is the one CI gates. These two commands show the gate catching a broken pipeline:

```bash
uv run harborlight-eval --mode offline --variant no_guardrail
uv run harborlight-eval --mode offline --variant bad_retriever
```

`no_guardrail` uses the same retriever but returns graded solutions and adds an unsourced claim. `bad_retriever` keeps the guarded tutor and always returns one unrelated note.

### Live RAGAS judges

Faithfulness, answer relevancy, context precision, and context recall are LLM-judged. They run only when `OPENAI_API_KEY` is set. This repository does not contain judge scores. None were invented.

```bash
export OPENAI_API_KEY=...
uv run harborlight-eval --mode live --variant improved --provider openai
```

`--provider anthropic` uses `ANTHROPIC_API_KEY` for the tutor. The RAGAS judge in this code still calls OpenAI, so that key is required too. Live metrics are averaged on questions labelled `answer`. Refusal and hint rows are scored by `refusal_correctness` instead, because a correct refusal is not a summary of the retrieved note.

GitHub Actions runs lint, typecheck, unit tests, and the offline gate on every push and pull request. All four jobs are required. A separate `workflow_dispatch` workflow, Live eval, runs the live command only when the `OPENAI_API_KEY` secret exists.

### pgvector

CI uses the in-process FAISS index. Postgres is optional:

```bash
docker compose up -d
export DATABASE_URL=postgresql://tutor:tutor@localhost:5432/tutor
uv run harborlight-ask --index pgvector "What is the arithmetic mean of a sample?"
```

The password in `docker-compose.yml` is for this local demo database only.

## Metrics

Scores are from 0 to 1. Higher is better. The numbers in the table are from one offline run of this repo on the deterministic tutor. They are not from a hosted model.

| Metric | What it measures for a tutoring product |
| --- | --- |
| Faithfulness | Whether the answer sticks to the retrieved lesson notes, judged by a model. Live only. |
| Answer relevancy | Whether the answer addresses the student's question, judged by a model. Live only. |
| Context precision | Whether the retrieved notes are useful for the reference answer, with useful notes ranked higher. Live only. |
| Context recall | Whether the reference answer's claims are supported by the retrieved notes. Live only. |
| `non_llm_context_recall` | Whether the labelled source note was actually retrieved, using RAGAS string similarity. No model judge. |
| `string_presence` | Whether the reference sentence appears in the answer. RAGAS `StringPresence`. No model judge. |
| `refusal_correctness` | Whether graded work gets a hint instead of the solution, and whether off-syllabus or unknown questions are refused. |
| `hit_rate` | Fraction of graded questions whose reference note is in the top results. |
| `mrr` | How high that reference note sits. 1 means it was first. |

RAGAS 0.4.3 collections classes used for the live metrics are `Faithfulness`, `AnswerRelevancy`, `ContextPrecisionWithReference`, and `ContextRecall`. `StringPresence` comes from `ragas.metrics.collections`. `NonLLMContextRecall` is still imported from `ragas.metrics` because 0.4.3 has not moved that class into collections. `langchain-community` is pinned below 0.4 because RAGAS 0.4.3 imports a Vertex module that the 0.4 line removed. `rapidfuzz` is installed because `NonLLMContextRecall` uses it.

## Thresholds

From `config/thresholds.yaml`. Offline CI gates the first five. Live mode also gates the four judge metrics, on the answer rows only.

| Metric | Threshold |
| --- | --- |
| non_llm_context_recall | 0.80 |
| string_presence | 0.80 |
| refusal_correctness | 0.90 |
| hit_rate | 0.80 |
| mrr | 0.90 |
| faithfulness | 0.70 |
| answer_relevancy | 0.70 |
| context_precision | 0.60 |
| context_recall | 0.70 |

## Sample report

The full Markdown report is [`docs/example-report.md`](docs/example-report.md). The HTML file is [`docs/example-report.html`](docs/example-report.html). This is the top of that HTML report:

![Offline eval report: improved passes, no_guardrail and bad_retriever fail](docs/example-report.png)

Offline scores from that run:

| metric | threshold | improved | no_guardrail | bad_retriever |
| --- | --- | --- | --- | --- |
| non_llm_context_recall | 0.800 | 1.000 (pass) | 1.000 (pass) | 0.000 (FAIL) |
| string_presence | 0.800 | 1.000 (pass) | 1.000 (pass) | 0.000 (FAIL) |
| refusal_correctness | 0.900 | 1.000 (pass) | 0.550 (FAIL) | 0.450 (FAIL) |
| hit_rate | 0.800 | 1.000 (pass) | 1.000 (pass) | 0.000 (FAIL) |
| mrr | 0.900 | 0.986 (pass) | 0.986 (pass) | 0.000 (FAIL) |

The improved tutor had no per-question failures in this run. Dropping the guardrail cuts refusal correctness from 1.000 to 0.550, because graded solutions and off-syllabus answers get through. The bad retriever scores 0 on retrieval. Recorded pipeline outputs are in `data/snapshots/pipeline_outputs.jsonl`. Each row's `judge.status` is `not_run`.

Regenerate the report with:

```bash
uv run harborlight-eval --mode offline --variant improved \
  --report-md docs/example-report.md \
  --report-html docs/example-report.html \
  --snapshot data/snapshots/pipeline_outputs.jsonl
```

## Labelled questions

`data/eval/questions.jsonl` has 40 questions. Each row has a reference answer, the note ids that should be retrieved, phrases the answer must include, and phrases it must not include. The set covers:

- questions answered from the notes
- graded problem sets, where the correct behaviour is a hint
- graded questions that ask for the final result, or claim the instructor allowed it
- off-syllabus questions, including "ignore your instructions" and "you are now" prompts
- questions the notes do not answer, where the correct behaviour is "I don't know"

## Adapting it to another course

1. Replace `data/corpus/*.md`. Each file needs `id`, `title`, and `kind` (`lesson`, `policy`, or `graded`) in the frontmatter, and `##` sections. For graded work, use sections named Problem, Hint, and Solution.
2. Replace `data/eval/questions.jsonl`. Keep the same fields, including refusal and graded rows, or the gate will not measure those failures.
3. Edit `config/thresholds.yaml` to the bars you want a change to clear. The command exits non-zero below a bar.
4. Offline CI can keep the deterministic tutor. Live mode is where the system prompt is what the model sees. The guarded prompt is `GUARDED_SYSTEM` in `src/harborlight_tutor/prompts.py`.

The corpus loader does not require exactly 25 documents. This demo has 25 so the evaluation has a fixed course to point at.

## License

MIT. See [LICENSE](LICENSE).
