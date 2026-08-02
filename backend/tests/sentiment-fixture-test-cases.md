# Test Cases: Sentiment Fixture API

## Overview

- Feature: local synthetic Bilibili comment fixture API
- Requirement: persist 20-30 fixed comments directly through an API, without calling comment crawling
- Entry point: `POST /api/test-fixtures/sentiment` with `BILI_ENABLE_TEST_FIXTURES=1`
- Expected workflow: create fixture -> open its history item -> run LLM reanalysis -> compare output with the expected labels below

## Fixture cases

| ID | Scenario | Expected emotion | Expected style | Parent relation |
|---|---|---|---|---|
| TC-01 | factual calculation | neutral | plain | root |
| TC-02 | factual question | neutral | plain | reply |
| TC-03 | factual answer | neutral | plain | nested reply |
| TC-04 | explicit appreciation | support | plain | reply |
| TC-05 | light self-joke | joy | plain | root |
| TC-06 | amused joke | joy | meme | reply |
| TC-07 | meme repetition | neutral | meme | nested reply |
| TC-08 | request for future topic | anticipation | plain | reply |
| TC-09 | clear unexpectedness | surprise | plain | root |
| TC-10 | belief reversal | surprise | plain | reply |
| TC-11 | risk question | concern | plain | reply |
| TC-12 | direct criticism | anger | plain | root |
| TC-13 | sarcastic criticism | anger | sarcasm | reply |
| TC-14 | rebuttal of sarcasm | anger | plain | nested reply |
| TC-15 | dislike of clickbait | disgust | plain | reply |
| TC-16 | personal loss memory | sadness | plain | root |
| TC-17 | empathetic support | support | plain | reply |
| TC-18 | sarcastic impossibility | disgust | sarcasm | root |
| TC-19 | practical concern | concern | plain | reply |
| TC-20 | absurd follow-up joke | joy | meme | nested reply |
| TC-21 | explicit endorsement | support | plain | root |
| TC-22 | neutral knowledge question | neutral | plain | reply |
| TC-23 | Bilibili short meme | surprise | meme | root |
| TC-24 | understanding acknowledgement | support | plain | reply |

## API and state tests

### TC-F-001: Create fixture

- Preconditions: service started with `BILI_ENABLE_TEST_FIXTURES=1`.
- Step: call `POST /api/test-fixtures/sentiment`.
- Expected result: a completed NLP analysis with exactly 24 comments is returned; no Bilibili request is made.

### TC-F-002: Read expected catalog

- Preconditions: fixture API enabled.
- Step: call `GET /api/test-fixtures/sentiment`.
- Expected result: all 24 IDs and their expected emotion/style pairs are returned.

### TC-ERR-001: Disable fixture API

- Preconditions: service started without the environment switch.
- Step: call either fixture endpoint.
- Expected result: API returns 404 and writes no test analysis.

## Coverage matrix

| Requirement | Test coverage |
|---|---|
| Direct fixture insertion without crawling | TC-F-001, automated route test |
| 20-30 realistic comments | TC-01 through TC-24 |
| Parent-child and nested reply context | TC-02/03, TC-06/07, TC-13/14, TC-18/20 |
| Neutral fallback evaluation | TC-01/02/03/07/22 |
| Meme and sarcasm evaluation | TC-06/07/13/18/20/23 |
| Disabled endpoint safety | TC-ERR-001, automated route test |
