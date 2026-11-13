Feature: Live recording
  A recording is transcribed while it is still going on, so that only the
  remainder and speaker identification are left when it ends.

  Background:
    Given the newest 1 second of a recording is held back

  @FR-50 @FR-51 @FR-52
  Scenario: Speech is transcribed while the recording is still going on
    When a recording "standup.webm" is started
    And this audio arrives for "standup.webm":
      | voice | says                     |
      | anna  | Good morning Ben.        |
      | ben   | Morning. Shall we start? |
      | anna  | Yes.                     |
    And the worker processes the queue
    Then the job for "standup.webm" is still recording
    And the text so far of "standup.webm" is "Good morning Ben. Morning. Shall we start?"
    And the output folder is empty

  @FR-51 @FR-52
  Scenario: Later passes continue where the previous one stopped
    Given a recording "standup.webm" is started
    And this audio arrives for "standup.webm":
      | voice | says              |
      | anna  | Good morning Ben. |
      | ben   | Morning.          |
    And the worker processes the queue
    When this audio arrives for "standup.webm":
      | voice | says            |
      | anna  | Shall we start? |
      | ben   | Yes.            |
    And the worker processes the queue
    Then the text so far of "standup.webm" is "Good morning Ben."
    When 30 seconds pass
    And the worker processes the queue
    Then the text so far of "standup.webm" is "Good morning Ben. Morning. Shall we start?"

  @FR-53
  Scenario: Speakers are identified when the recording ends
    Given a recording "standup.webm" is started
    And this audio arrives for "standup.webm":
      | voice | says                     |
      | anna  | Good morning Ben.        |
      | ben   | Morning. Shall we start? |
      | anna  | Yes.                     |
    And the worker processes the queue
    When the recording "standup.webm" is finished
    And the worker processes the queue
    Then the job for "standup.webm" is done
    And the job for "standup.webm" is no longer recording
    And the job for "standup.webm" reports 2 speakers
    And the output file "standup.md" contains:
      """
      **Speaker 1** `[00:00:00]`

      Good morning Ben.

      **Speaker 2** `[00:00:02]`

      Morning. Shall we start?

      **Speaker 1** `[00:00:04]`

      Yes.
      """
    And the archive folder contains "standup.webm"
    And no staged files remain

  @FR-53
  Scenario: A recording that ends before any pass is transcribed in one go
    Given a recording "memo.webm" is started
    And this audio arrives for "memo.webm":
      | voice | says            |
      | anna  | Note to myself. |
    When the recording "memo.webm" is finished
    And the worker processes the queue
    Then the job for "memo.webm" is done
    And the output file "memo.md" contains:
      """
      Note to myself.
      """

  @FR-54
  Scenario: Nothing has been transcribed before the first pass
    When a recording "standup.webm" is started
    Then the text so far of "standup.webm" is ""
    When the worker processes the queue
    Then the job for "standup.webm" is still recording
    And the job for "standup.webm" took 0 attempts

  @FR-55
  Scenario: A piece of audio that is sent twice is stored once
    Given a recording "standup.webm" is started
    And this audio arrives for "standup.webm":
      | voice | says              |
      | anna  | Good morning Ben. |
    When the last piece of "standup.webm" is sent again
    And the recording "standup.webm" is finished
    And the worker processes the queue
    Then the output file "standup.md" contains:
      """
      Good morning Ben.
      """
    And the output file "standup.md" does not contain "Ben. Good"

  @FR-55
  Scenario: A piece of audio that would leave a gap is refused
    Given a recording "standup.webm" is started
    When a piece of audio arrives for "standup.webm" that skips ahead
    Then the request is refused because audio is missing before it

  @FR-56
  Scenario: A recording that stops receiving audio is finished automatically
    Given a recording "standup.webm" is started
    And this audio arrives for "standup.webm":
      | voice | says              |
      | anna  | Good morning Ben. |
    And the worker processes the queue
    When 120 seconds pass
    And the worker processes the queue
    Then the job for "standup.webm" is still recording
    When 31 seconds pass
    And the worker processes the queue
    Then the job for "standup.webm" is done
    And the output file "standup.md" contains:
      """
      Good morning Ben.
      """

  @FR-57
  Scenario: A recording in progress does not block other files
    Given a recording "standup.webm" is started
    And this audio arrives for "standup.webm":
      | voice | says              |
      | anna  | Good morning Ben. |
    And the worker processes the queue
    And a queued recording "call.mp3"
    When the worker processes the queue
    Then the job for "call.mp3" is done
    And the job for "standup.webm" is still recording
    And the job for "standup.webm" took 0 attempts

  @FR-57 @FR-34
  Scenario: What was transcribed survives a worker crash
    Given a recording "standup.webm" is started
    And this audio arrives for "standup.webm":
      | voice | says              |
      | anna  | Good morning Ben. |
      | ben   | Morning.          |
    And the worker processes the queue
    And 30 seconds pass
    And a worker crashes while processing "standup.webm"
    And this audio arrives for "standup.webm":
      | voice | says            |
      | anna  | Shall we start? |
    When 121 seconds pass
    And the housekeeper runs
    And this audio arrives for "standup.webm":
      | voice | says |
      | ben   | Yes. |
    And the worker processes the queue
    Then the job for "standup.webm" is still recording
    And the text so far of "standup.webm" is "Good morning Ben. Morning. Shall we start?"

  @FR-33 @FR-50
  Scenario: Audio that cannot be decoded only fails the recording once it has ended
    Given a recording "standup.webm" is started
    And a piece of audio arrives for "standup.webm" that cannot be decoded
    When the worker processes the queue
    Then the job for "standup.webm" is still recording
    When the recording "standup.webm" is finished
    And the worker processes the queue
    Then the job for "standup.webm" is failed
    And the failed folder contains "standup.webm"

  @FR-58
  Scenario: A cancelled recording accepts no more audio
    Given a recording "standup.webm" is started
    When the job for "standup.webm" is cancelled
    And a piece of audio arrives for "standup.webm"
    Then the request is refused because the recording is closed

  @FR-58
  Scenario: A finished recording accepts no more audio
    Given a recording "standup.webm" is started
    And this audio arrives for "standup.webm":
      | voice | says              |
      | anna  | Good morning Ben. |
    And the recording "standup.webm" is finished
    When a piece of audio arrives for "standup.webm"
    Then the request is refused because the recording is closed

  @FR-58
  Scenario: A recording without any audio is dropped when it is finished
    Given a recording "standup.webm" is started
    When the recording "standup.webm" is finished
    Then the request is refused because nothing was recorded
    And no job exists
    And no staged files remain

  @FR-53 @FR-40
  Scenario: A finished recording can be run again from its archived audio
    Given a recording "standup.webm" is started
    And this audio arrives for "standup.webm":
      | voice | says              |
      | anna  | Good morning Ben. |
      | ben   | Morning.          |
    And the worker processes the queue
    And the recording "standup.webm" is finished
    And the worker processes the queue
    When the job for "standup.webm" is retried
    And the worker processes the queue
    Then the job for "standup.webm" is done
    And the output file "standup.md" contains:
      """
      **Speaker 2** `[00:00:02]`

      Morning.
      """
