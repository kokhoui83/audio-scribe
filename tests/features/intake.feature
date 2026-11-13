Feature: Watching the inbox folder
  Audio files dropped into the inbox are queued for transcription without
  any further action by the operator.

  @FR-01 @FR-02
  Scenario: A dropped audio file is queued once it has stopped changing
    Given a recording "call.mp3" is dropped in the inbox
    When the watcher scans the inbox
    Then no job exists
    When 5 seconds pass
    And the watcher scans the inbox
    Then the job for "call.mp3" is queued
    And the inbox is empty

  @FR-02
  Scenario: A file that is still being copied is left alone
    Given a recording "call.mp3" is dropped in the inbox
    And the watcher scans the inbox
    When 4 seconds pass
    And more data is written to "call.mp3" in the inbox
    And the watcher scans the inbox
    And 4 seconds pass
    And the watcher scans the inbox
    Then no job exists
    And "call.mp3" is still in the inbox

  @FR-02
  Scenario: An empty file is not queued
    Given an empty file "call.mp3" is dropped in the inbox
    When the watcher has seen the inbox unchanged for 5 seconds
    Then no job exists

  @FR-03
  Scenario Outline: Files that are not audio are left untouched
    Given a recording "<file>" is dropped in the inbox
    When the watcher has seen the inbox unchanged for 5 seconds
    Then no job exists
    And "<file>" is still in the inbox

    Examples:
      | file              |
      | notes.txt         |
      | README            |
      | .hidden.mp3       |
      | call.mp3.part     |
      | call.mp3.crdownload |
      | .cache/call.mp3   |

  @FR-04
  Scenario Outline: Popular audio and video formats are accepted
    Given a recording "<file>" is dropped in the inbox
    When the watcher has seen the inbox unchanged for 5 seconds
    Then the job for "<file>" is queued

    Examples:
      | file         |
      | a.mp3        |
      | a.WAV        |
      | a.m4a        |
      | a.flac       |
      | a.ogg        |
      | a.opus       |
      | a.aac        |
      | a.wma        |
      | a.mp4        |
      | a.webm       |

  @FR-01 @FR-20
  Scenario: Sub-folders are watched and mirrored in the output folder
    Given a recording "team/weekly/standup.wav" is dropped in the inbox
    When the watcher has seen the inbox unchanged for 5 seconds
    And the worker processes the queue
    Then the output folder contains "team/weekly/standup.md"
    And the archive folder contains "team/weekly/standup.wav"

  @FR-37
  Scenario: A file taken from the inbox but never registered as a job is put back
    Given "lost.mp3" was taken from the inbox by a watcher that crashed before registering the job
    When the system recovers orphaned files
    Then "lost.mp3" is still in the inbox
