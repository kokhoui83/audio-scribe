Feature: Managing jobs
  What the web page and the HTTP API let a user do.

  @FR-05
  Scenario: A file is uploaded with its own options
    When "interview.m4a" is uploaded with language "fr" and 2 speakers
    Then the job for "interview.m4a" is queued
    When the worker processes the queue
    Then the job for "interview.m4a" is done
    And the job for "interview.m4a" reports the language "fr"
    And the speaker model was told to expect 2 speakers

  @FR-05 @FR-12
  Scenario: Speaker identification is turned off for one upload
    When "memo.m4a" is uploaded without speaker identification
    And the worker processes the queue
    Then the job for "memo.m4a" reports 0 speakers

  @FR-22
  Scenario Outline: Any format can be fetched for a finished job
    Given a finished recording "call.mp3"
    When the transcript of "call.mp3" is requested as "<format>"
    Then the response starts with "<start>"

    Examples:
      | format | start      |
      | md     | # call.mp3 |
      | txt    | [00:00:00] |
      | json   | {          |
      | srt    | 1          |
      | vtt    | WEBVTT     |

  @FR-22
  Scenario: A transcript is not available before the job is done
    Given a queued recording "call.mp3"
    When the transcript of "call.mp3" is requested as "md"
    Then the request is refused because the transcript is not ready

  @FR-25
  Scenario: Speakers are given real names
    Given the output formats are "md, srt"
    And a finished recording "meeting.mp3" in which:
      | voice | says               |
      | anna  | Good morning Ben.  |
      | ben   | Good morning Anna. |
    When the speakers of "meeting.mp3" are named:
      | label     | name |
      | Speaker 1 | Anna |
      | Speaker 2 | Ben  |
    Then the output file "meeting.md" contains:
      """
      **Anna** `[00:00:00]`
      """
    And the output file "meeting.srt" contains:
      """
      [Ben] Good morning Anna.
      """
    And the output file "meeting.md" does not contain "Speaker 1"

  @FR-40
  Scenario: A failed job is run again
    Given a queued file "call.mp3" that cannot be decoded
    And the worker processes the queue
    And the file "call.mp3" in the failed folder is replaced by a proper recording
    When the job for "call.mp3" is retried
    And the worker processes the queue
    Then the job for "call.mp3" is done
    And the output folder contains "call.md"
    And the archive folder contains "call.mp3"
    And the failed folder is empty

  @FR-40
  Scenario: A job cannot be run again once its original is gone
    Given originals are not archived
    And a finished recording "call.mp3"
    When the job for "call.mp3" is retried
    Then the request is refused because the original file is gone
    And the job for "call.mp3" is done

  @FR-40
  Scenario: A queued job is cancelled
    Given a queued recording "call.mp3"
    When the job for "call.mp3" is cancelled
    And the worker processes the queue
    Then the job for "call.mp3" is cancelled
    And the output folder is empty

  @FR-40
  Scenario: A finished job cannot be cancelled
    Given a finished recording "call.mp3"
    When the job for "call.mp3" is cancelled
    Then the request is refused because the job is done

  @FR-40
  Scenario: Deleting a job keeps its transcript but not its staged file
    Given a queued recording "a.mp3"
    And a finished recording "b.mp3"
    When the job for "a.mp3" is deleted
    And the job for "b.mp3" is deleted
    Then no job exists
    And no staged files remain
    And the output folder contains "b.md"

  @FR-42
  Scenario: The health report counts jobs and lists workers
    Given a finished recording "a.mp3"
    And a queued recording "b.mp3"
    Then the health report counts 1 done and 1 queued job
    And the health report lists 1 worker that is alive
    When 60 seconds pass
    Then the health report lists 1 worker that is not alive
