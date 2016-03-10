import itertools
import os
import re
import sys
import math
import textwrap
from collections import Counter

class Program(object):
    def __init__(self, use_delays):
        super(Program, self).__init__()
        self._use_delays = use_delays

    def add_note(self, count, pitch, duration, delay, volume, time):
        raise NotImplementedError("Subclasses must implement `add_note`")

    def add_silent_note(self, count, duration, delay, volume, time):
        raise NotImplementedError("Subclasses must implement `add_silent_note`")

    def count_notes(self):
        raise NotImplementedError("Subclasses must implement `count_notes`")

    @property
    def use_delays(self):
        return self._use_delays

class Program_Zumo(Program):
    def __init__(self, use_delays):
        super(Program_Zumo, self).__init__(use_delays)
        self.notes = []
        self.durations = []
        self.delays = []
        self.volumes = []
        self._midi_volume = 127.0
        self._min_volume = 9
        self._max_volume = 15
        self._volume_adjust = -2

    def count_notes(self):
        return len(self.notes)

    def _make_volume(self, volume):
        # Convert MIDI volume
        v = volume/self._midi_volume * self._max_volume + self._volume_adjust
        return max(self._min_volume, int(v))

    def _add_note(self, n, note, duration, delay, volume):
        self.notes[n-1:n-1] = [note]
        self.durations[n-1:n-1] = [duration]
        self.delays[n-1:n-1] = [delay]
        self.volumes[n-1:n-1] = [self._make_volume(volume)]

    def check(self):
        volume = None
        if all(self.volumes[0] == v for v in self.volumes):
            volume = self.volumes[0]
            print("Volume: {}".format(volume))

        duration_delay = all(duration == delay for duration, delay in itertools.izip(self.durations, self.delays))

        print("Durations are {0}equal to delays; {0}all notes are nonoverlapping.".format("" if duration_delay else "not "))
        print("Use of delays {} according to setting.".format("enabled" if self.use_delays else "disabled"))

        return volume, duration_delay

class Program_Array(Program_Zumo):
    def __init__(self, use_delays):
        super(Program_Array, self).__init__(use_delays)
        self.tones = (
            "C", "C_SHARP", "D", "D_SHARP", "E", "F", "F_SHARP", "G", "G_SHARP",
            "A", "A_SHARP", "B"
        )

    def add_note(self, count, pitch, duration, delay, volume):
        macro = "NOTE_{}({})".format(self.tones[pitch % 12], pitch/12)
        self._add_note(count, macro, duration, delay, volume)

    def add_silent_note(self, count, duration, delay, volume):
        macro = "SILENT_NOTE"
        self._add_note(count, macro, duration, delay, volume)

    def write(self, filename):
        volume, duration_delay = self.check()

        f = open(filename, 'w')
        f.write("""#include <ZumoBuzzer.h>
#include <Pushbutton.h>

#define LED_PIN 13

""")
        f.write("#define MELODY_LENGTH {}\n".format(self.count_notes()))
        self._write_array(f, 'char', 'notes', self.notes)
        self._write_array(f, 'int', 'durations', self.durations)
        if self.use_delays and not duration_delay:
            self._write_array(f, 'int', 'delays', self.delays)
        if volume is None:
            self._write_array(f, 'int', 'volumes', self.volumes)

        f.write("""
ZumoBuzzer buzzer;
Pushbutton button(ZUMO_BUTTON);
unsigned int currentIdx;

void setup()
{
  currentIdx = 0;

  pinMode(LED_PIN, OUTPUT);

  // Wait for button to play the melody.
  button.waitForButton();
}

void loop()
{
""")
        f.write("  if (currentIdx < MELODY_LENGTH{})".format(" && !buzzer.isPlaying()" if duration_delay or not self.use_delays else ""))
        f.write("""
  {
    if (notes[currentIdx] == SILENT_NOTE)
    {
      digitalWrite(LED_PIN, LOW);
    }
    else
    {
      digitalWrite(LED_PIN, HIGH);
    }
""")
        f.write("    buzzer.playNote(notes[currentIdx], durations[currentIdx], {});\n".format(volume if volume is not None else "volumes[currentIdx]"))
        if self.use_delays:
            f.write("    delay({}[currentIdx]);\n".format("durations" if duration_delay else "delays"))
        f.write("""
    currentIdx++;
  }
  else if (currentIdx >= MELODY_LENGTH) {
    digitalWrite(LED_PIN, LOW);
  }

  // let the user pushbutton function as a stop/reset melody button
  if (button.isPressed())
  {
    buzzer.stopPlaying();
    digitalWrite(LED_PIN, LOW);
    if (currentIdx < MELODY_LENGTH)
    {
      // terminate the melody
      currentIdx = MELODY_LENGTH;
    }
    else
    {
      // restart the melody
      currentIdx = 0;
    }
    // wait here for the button to be released
    button.waitForRelease();
  }
}
""")

        f.close()

    def _write_array(self, f, data_type, name, data):
        lines = ', '.join([str(d) for d in data])
        f.write("\nconst unsigned {} {}[MELODY_LENGTH] =".format(data_type, name))
        f.write("\n{\n")
        f.write("  {}\n".format('\n  '.join(textwrap.wrap(lines))))
        f.write("};\n")

class Program_Sequence(Program_Zumo):
    def __init__(self, use_delays):
        super(Program_Sequence, self).__init__(use_delays)
        self.tones = (
            "c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b"
        )
        self.octaves = []
        # Baseline BPM for quarter notes
        self._BPM = 120.0
        # Quarter notes value
        self._note_value = 4

    def add_note(self, count, pitch, duration, delay, volume):
        note = self.tones[pitch % 12]
        self._add_note(count, note, duration, delay, volume)
        self.octaves[count-1:count-1] = [pitch/12]

    def add_silent_note(self, count, duration, delay, volume):
        self._add_note(count, "R", duration, delay, volume)

    def write(self, filename):
        volume, duration_delay = self.check()

        f = open(filename, 'w')
        f.write("""#include <ZumoBuzzer.h>
#include <Pushbutton.h>
#include <avr/pgmspace.h>

""")

        melody = ""
        if volume is not None:
            melody += "V{} ".format(volume)

        octave = Counter(self.octaves).most_common(1)[0][0]
        melody += "O{} ".format(octave-1)

        beats = self._BPM*60*self.count_notes()
        length = sum(self.durations)
        tempo = int(math.ceil(beats/float(length)))
        melody += "T{} ".format(tempo)

        for note, duration, delay, pitch, volume in zip(self.notes, self.durations, self.delays, self.octaves, self.volumes):
            if note == "R":
                duration = 0
            else:
                v = "V{} ".format(volume) if volume is None else ""
                o = octave - pitch
                ox = ">" * o if o > 0 else "<" * o
                d = int(math.ceil(self._BPM*1/float(duration)))
                melody += "{}{}{}{}".format(v, ox, note, d if d > 1 else "")

            rest = delay - duration
            if rest > 0:
                note_rest = self._note_value**2
                melody += "R" * int(math.floor((60*rest)/(note_rest*self._BPM)))

        f.write('const char melody[] PROGMEM = "{}";\n'.format(melody))
        f.write("""
ZumoBuzzer buzzer;
Pushbutton button(ZUMO_BUTTON);

void setup()
{
  // Wait for button to play the melody.
  button.waitForButton();
}

void loop()
{
  buzzer.playFromProgramSpace(melody);
  button.waitForPress();
  if (buzzer.isPlaying())
  {
    buzzer.stopPlaying();
    button.waitForRelease();
    button.waitForButton();
  }
  else {
    button.waitForRelease();
  }
}
""")

class Reader(object):
    def __init__(self, filename, f, use_delays=True, program_class=Program_Sequence):
        super(Reader, self).__init__()
        self.filename = filename
        self.file = f
        self.use_delays = use_delays
        self._program_class = program_class

        self.ntracks = 1
        self.track = 0
        self._reset_state()

    def _note_on(self, time, note, volume):
        if len(self.notes) == 0:
            duration = time - self.last_time
            if duration > 0:
                self.note_count += 1
                n = self.note_count
                self.program.add_silent_note(n, duration, duration, volume)
                self.times[n-1:n-1] = [time]
        else:
            self.warnings.add("Multiple notes are playing at the same time.")

        if note in self.notes:
            self.warnings.add("There is a note that is turned on without being turned off beforehand.")
        else:
            self.note_count += 1
            self.notes[note] = (self.note_count, time, volume)

    def _note_off(self, time, note):
        if note in self.notes:
            duration = time - self.notes[note][1]

            n = self.notes[note][0]
            if n >= len(self.times):
                delay = duration
            else:
                # Adjust delay for out-of-order note
                delay = self.times[n-1] - time

            volume = self.notes[note][2]
            self.program.add_note(n, note, duration, delay, volume)
            self.times[n-1:n-1] = [time]
            self.last_time = max(self.last_time, time)
            del self.notes[note]

    def _reset_state(self):
        self.program = self._program_class(self.use_delays)
        self.times = []
        self.warnings = set()
        self.note_count = 0
        self.last_time = 0
        self.notes = {}
        self.name = ""

    def _end_track(self):
        print('Track #{}, Name: "{}"'.format(self.track, self.name))
        for warning in self.warnings:
            print(warning)
        if self.program.count_notes() == 0:
            print("Empty track, no file written.")
            self._reset_state()
            return

        t = re.sub(r'[^\w]+', '', self.name)
        program_file = "{}-{}-{}.ino".format(self.filename, self.track, t)
        self.program.write(program_file)
        self._reset_state()

    def read(self):
        for line in self.file:
            parts = line.strip().split(' ')
            if parts[0] == "MFile":
                self.ntracks = int(parts[2])
            elif parts[0] == "MTrk":
                self.track += 1
            elif parts[0] == "TrkEnd":
                self._end_track()
            elif len(parts) > 1:
                if parts[1] == "Meta":
                    if parts[2] == "SeqName" or parts[2] == "TrkName":
                        self.name = ' '.join(parts[3:]).strip('" ')
                elif parts[1] == "On":
                    time = int(parts[0])
                    note = int(parts[3][2:])
                    volume = int(parts[4][2:])
                    if volume == 0:
                        self._note_off(time, note)
                    else:
                        self._note_on(time, note, volume)
                elif parts[1] == "Off":
                    time = int(parts[0])
                    note = int(parts[3][2:])
                    self._note_off(time, note)

def main(argv):
    filename = argv[0] if len(argv) > 0 else "midi"

    f = None
    if sys.stdin.isatty():
        if os.path.exists(filename):
            f = open(filename, 'r')
            filename = os.path.splitext(filename)
        elif os.path.exists("{}.mid".format(filename)):
            f = open("{}.mid".format(filename), 'r')
    else:
        f = sys.stdin

    if f is None:
        print("No suitable midi dump file provided")
        return 1

    reader = Reader(filename, f)
    reader.read()

    f.close()

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
