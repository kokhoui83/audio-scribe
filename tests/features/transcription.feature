Feature: Transcribing recordings
  A queued recording becomes a transcript that says who spoke when.

  @FR-10 @FR-11 @FR-20 @FR-24
  Scenario: A conversation is transcribed with distinct speakers
    Given a queued recording "meeting.mp3" in which:
      | voice | says                     |
      | anna  | Good morning Ben.        |
      | ben   | Morning. Shall we start? |
      | anna  | Yes.                     |
    When the worker processes the queue
    Then the job for "meeting.mp3" is done
    And the job for "meeting.mp3" reports 2 speakers
    And the output file "meeting.md" contains:
      """
      **Speaker 1** `[00:00:00]`

      Good morning Ben.

      **Speaker 2** `[00:00:02]`

      Morning. Shall we start?

      **Speaker 1** `[00:00:04]`

      Yes.
      """
    And the archive folder contains "meeting.mp3"
    And the inbox is empty

  @FR-12
  Scenario: Speaker identification is turned off for the whole system
    Given speaker identification is turned off
    And a queued recording "memo.mp3" in which:
      | voice | says            |
      | anna  | Note to myself. |
    When the worker processes the queue
    Then the job for "memo.mp3" is done
    And the job for "memo.mp3" reports 0 speakers
    And the output file "memo.md" does not contain "Speaker"

  @FR-10
  Scenario: The spoken language is detected when none is given
    Given a queued recording "call.mp3"
    When the worker processes the queue
    Then the job for "call.mp3" reports the language "en"

  @FR-10
  Scenario: A default language is passed to the recogniser
    Given the default language is "de"
    And a queued recording "anruf.mp3"
    When the worker processes the queue
    Then the job for "anruf.mp3" reports the language "de"

  @FR-14
  Scenario: A recording without speech gives an empty transcript
    Given a queued recording "silence.wav" without speech
    When the worker processes the queue
    Then the job for "silence.wav" is done
    And the output file "silence.md" contains:
      """
      _No speech detected._
      """

  @FR-21
  Scenario: Markdown is the only format written by default
    Given a queued recording "call.mp3"
    When the worker processes the queue
    Then the output folder contains only "call.md"

  @FR-21
  Scenario: Every configured format is written
    Given the output formats are "md, json, srt, vtt, txt"
    And a queued recording "call.mp3"
    When the worker processes the queue
    Then the output folder contains "call.md"
    And the output folder contains "call.json"
    And the output folder contains "call.srt"
    And the output folder contains "call.vtt"
    And the output folder contains "call.txt"

  @FR-23
  Scenario: A second file with the same name does not overwrite the first transcript
    Given a queued recording "call.mp3" in which:
      | voice | says        |
      | anna  | First call. |
    And the worker processes the queue
    And a queued recording "call.mp3" in which:
      | voice | says         |
      | anna  | Second call. |
    When the worker processes the queue
    Then the output file "call.md" contains:
      """
      First call.
      """
    And 2 transcripts exist in the output folder
    And 2 originals exist in the archive folder

  @FR-24
  Scenario: Originals are deleted when archiving is turned off
    Given originals are not archived
    And a queued recording "call.mp3"
    When the worker processes the queue
    Then the job for "call.mp3" is done
    And the archive folder is empty
    And no staged files remain
