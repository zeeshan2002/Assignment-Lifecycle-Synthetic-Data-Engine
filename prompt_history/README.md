# Assignment Management System --- Prompt History

## Overview

This folder contains the development prompt history for the Assignment
Management System assessment.

The prompt history documents the sequence of development activities,
including project planning, database design, synthetic data generation,
business logic, anomaly testing, validation, exports and final
verification.

## Files

  -------------------------------------------------------------------------------
  File                                        Description
  ------------------------------------------- -----------------------------------
  `prompt_history.md`   Contains the 12 development prompts
                                              in chronological order, along with
                                              implementation notes.

  -------------------------------------------------------------------------------

## How to Use

1.  Open `prompt_history.md`.
2.  Review the prompts in sequence.
3.  Use them as a record of the development workflow and the tasks
    addressed during implementation.

## Technology and Implementation Notes

The prompt history reflects the implementation approach described for
this project:

-   Python's built-in `csv` module for CSV reading and writing.
-   Python's built-in `random` module, wrapped by a custom PRNG utility
    for repeatable random streams.
-   Predefined lists for synthetic names and values; Faker is not used.
-   Plain Python calculations; Pandas is not used.
-   Python's built-in `sqlite3` module for creating and verifying the
    SQLite database.
-   Plain-text SQL files for the schema and seed data.

## Accuracy Note

This document is a record of prompts and intended development tasks. It
should not be treated as proof that every task was completed. The actual
source code, test results, generated datasets and validation reports are
the evidence of implementation.
