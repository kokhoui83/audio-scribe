"""The text of a recording so far, and which newly recognised words are kept."""

import pytest

from scribe.domain.draft import Draft
from scribe.domain.transcript import Word

MARGIN = 5.0


def words(*specs) -> list[Word]:
    """spec: (start, end, text, recogniser segment)."""
    return [Word(s[0], s[1], s[2], segment=s[3]) for s in specs]


def heard(draft: Draft, new, seconds, *, final=False, language="en") -> Draft:
    return draft.extended(new, seconds=seconds, language=language, final=final, margin=MARGIN)


TWO_SENTENCES = words(
    (0.0, 1.0, " Good", 0), (1.0, 2.0, " morning.", 0), (3.0, 4.0, " Shall", 1), (4.0, 5.0, " we?", 1)
)  # fmt: skip


class TestSettling:
    def test_a_new_draft_is_empty(self):
        assert (Draft().position, Draft().text, Draft().words, Draft().language) == (0.0, "", (), None)

    def test_sentences_that_ended_before_the_margin_are_kept(self):
        draft = heard(Draft(), TWO_SENTENCES, seconds=8.0)
        assert draft.text == "Good morning."

    def test_the_next_pass_starts_in_the_pause_after_the_last_kept_sentence(self):
        draft = heard(Draft(), TWO_SENTENCES, seconds=8.0)
        assert draft.position == pytest.approx(2.5)  # between "morning." and "Shall"

    def test_the_cut_never_reaches_into_the_margin(self):
        late = words((0.0, 1.0, " Good", 0), (1.0, 2.0, " morning.", 0), (7.5, 8.0, " Shall", 1))
        assert heard(Draft(), late, seconds=8.0).position == pytest.approx(3.0)

    def test_a_sentence_is_never_cut_in_two(self):
        one_sentence = words((0.0, 1.0, " Good", 0), (1.0, 2.0, " morning", 0), (9.0, 9.5, " everyone.", 0))
        draft = heard(Draft(), one_sentence, seconds=10.0)
        assert (draft.text, draft.position) == ("", 0.0)

    def test_nothing_is_kept_while_there_is_less_audio_than_the_margin(self):
        draft = heard(Draft(), words((0.0, 1.0, " Hi.", 0)), seconds=4.0)
        assert (draft.text, draft.position) == ("", 0.0)

    def test_when_all_speech_ended_before_the_margin_everything_is_kept(self):
        draft = heard(Draft(), TWO_SENTENCES, seconds=20.0)
        assert draft.text == "Good morning. Shall we?"
        assert draft.position == pytest.approx(15.0)

    def test_silence_is_skipped_up_to_the_margin(self):
        draft = heard(Draft(), [], seconds=30.0)
        assert (draft.text, draft.position) == ("", 25.0)

    def test_speech_without_any_sentence_end_is_cut_between_words_after_a_minute(self):
        drone = words(*((float(i), i + 0.9, f" w{i}", 0) for i in range(70)))
        draft = heard(Draft(), drone, seconds=70.0)
        assert draft.words[-1].text == " w64" and draft.position == pytest.approx(64.95)


class TestContinuing:
    def test_new_words_are_placed_after_the_position(self):
        first = heard(Draft(), TWO_SENTENCES, seconds=8.0)
        second = heard(first, words((0.5, 1.5, " Shall", 0), (1.5, 2.5, " we?", 0)), seconds=20.0)
        assert second.text == "Good morning. Shall we?"
        assert [(w.start, w.end) for w in second.words[2:]] == [(3.0, 4.0), (4.0, 5.0)]
        assert second.position == pytest.approx(2.5 + 15.0)

    def test_sentences_of_a_later_pass_stay_distinct_from_earlier_ones(self):
        first = heard(Draft(), TWO_SENTENCES, seconds=8.0)
        second = heard(first, words((0.5, 1.5, " Shall", 0), (1.5, 2.5, " we?", 0)), seconds=20.0)
        assert [w.segment for w in second.words] == [0, 0, 1, 1]

    def test_the_language_found_first_is_kept(self):
        first = heard(Draft(), TWO_SENTENCES, seconds=8.0, language="de")
        assert heard(first, [], seconds=1.0, language="en").language == "de"
        assert heard(Draft(), [], seconds=1.0, language=None).language is None


class TestFinishing:
    def test_at_the_end_of_the_recording_every_word_is_kept(self):
        draft = heard(Draft(), TWO_SENTENCES, seconds=5.5, final=True)
        assert draft.text == "Good morning. Shall we?"
        assert draft.position == 5.5


class TestStoring:
    def test_a_draft_survives_being_stored(self):
        draft = heard(heard(Draft(), TWO_SENTENCES, seconds=8.0), TWO_SENTENCES, seconds=20.0)
        restored = Draft.from_dict(draft.to_dict())
        assert restored == draft
        assert [w.segment for w in restored.words] == [w.segment for w in draft.words]

    def test_nothing_stored_is_an_empty_draft(self):
        assert Draft.from_dict(None) == Draft()
