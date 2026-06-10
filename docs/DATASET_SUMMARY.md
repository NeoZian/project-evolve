# Dataset Summary for Presentation

Project Evolve uses a hybrid data strategy: public datasets for realistic student feedback and teaching indicators, plus synthetic institutional data for sensitive or unavailable components.

## 1. `ratemyprofessor_sample.csv`

This is the main active dataset in the prototype. It provides professor names, departments, numerical student ratings, and qualitative student comments. It supports the student feedback table, NLP sentiment analysis, topic analysis, and the student-feedback component of the final evaluation score.

## 2. `teaching-quality-evaluation-dataset.csv`

This is a supplementary structured dataset. It contains teaching indicators such as attendance, student average score, teacher evaluation score, technology integration, research publications, and teaching-quality labels. It is integrated into the data layer to support multi-source design, but it is not the main active scoring source in the current prototype.

## 3. `online-teaching-feedback-analytics-dataset.csv`

This is a supplementary online-learning dataset. It includes online feedback text, satisfaction score, engagement score, assignment score, final grade, and platform-access information. It helps represent online teaching effectiveness and student engagement, but it is not deeply connected to the final scoring formula yet.

## Synthetic data

Synthetic data is used for peer reviews, anonymised performance metrics, course materials, course-quality scores, service contributions, professional-development records, ethics-board records, audit logs, and bias-testing cases. This is necessary because complete institutional faculty-evaluation data is sensitive and usually unavailable publicly.

## Presentation summary

All three datasets are used in the data aggregation stage. The RateMyProfessor dataset is the main active dataset for NLP and student feedback scoring. The teaching-quality and online-teaching datasets are supplementary sources that demonstrate the framework's multi-source design and provide a clear path for future integration. Synthetic data fills the institutional fields required by the project and enables safe testing of fairness, XAI, and blockchain audit features.
