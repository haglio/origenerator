"""Where a new generation joins the line, and which of the waiting ones starts next.

Origenerator keeps the line itself and hands ComfyUI one prompt at a time. It has
to: ComfyUI's queue is a heap ordered by submit, it has no pause, and a prompt
already on it can only be dropped or interrupted — a run that has begun cannot be
set down and picked back up. So a queue that means to change its mind has to do
it before the prompt is sent, which means holding the line on this side of the
wire.

Two rules, and both are about what the user is doing while the GPU works:

* **An image joins the front, newest first.** A picture is seconds of GPU and it
  is usually the thing being waited for — a fresh variation, an enhancement of
  what is on screen. Asking for one means "now", so it starts next, ahead of
  everything that hasn't started yet.
* **A video joins the back.** Minutes of GPU, and asking for one means "later":
  it waits behind every image, and behind every video asked for before it. That
  is what keeps a handful of queued videos from taking the machine away from the
  work in front of the user. A chained i2v's start frame counts as the video it
  opens, not as the picture it draws: placed by what its own prompt makes, it
  would take the very front, and asking for a video would land it ahead of every
  picture already waiting.

Work nobody asked for — a background experiment, a base re-render — never joins
the front whatever it makes, because putting one in front of the user's own work
would be the whole cost of the feature.

And one gate: **while the slideshow is playing, no video starts.** A video
generation saturates the GPU the show is being drawn with, and a show is exactly
when nobody is waiting for a video. So a video that comes up while one plays is
passed over — every image behind it goes first — and with nothing but videos
left the line simply holds until an image is asked for or the show ends.

Pure ordering, no Qt and no server: it works on anything carrying a
``media_type`` ("image"/"video"), an optional ``run_media_type`` for a stage whose
run makes something other than what it makes itself, and a ``source`` — which is
what makes the queue's behavior testable without a running ComfyUI.
"""

# The ``source`` of work the user asked for, as opposed to a background
# experiment ("experiment") or a repair of an old row ("base_render").
USER_SOURCE = "generated"


def is_video(job) -> bool:
    """Whether this job belongs to a video run — minutes of GPU rather than seconds.

    ``run_media_type`` is what the *run* will produce, which is not always what
    this prompt outputs: a chained i2v draws its start frame first, and that
    still is the opening of a video. A job that declares no run type is read by
    what it makes itself.
    """
    return (getattr(job, "run_media_type", None)
            or getattr(job, "media_type", None)) == "video"


def joins_the_front(job) -> bool:
    """Whether this job jumps the line: the user's own image work, and only that.

    A background experiment or a base re-render makes images too, but it is work
    the user never asked for and there can be a great many of them, so they take
    the back of the line like anything else.
    """
    return not is_video(job) and getattr(job, "source", USER_SOURCE) == USER_SOURCE


def insertion_index(line: list, job) -> int:
    """Where ``job`` joins ``line`` — the front for an image, the back otherwise.

    The front is index 0 rather than "ahead of the videos": images stack newest
    first, so the last picture asked for is the next one made. That is the whole
    point of putting them there — the user asks for a variation because they are
    looking at the one before it.
    """
    return 0 if joins_the_front(job) else len(line)


def next_ready(line: list, *, videos_held: bool):
    """The first job in ``line`` that may start now, or ``None`` if none may.

    With videos held, a video is passed over rather than moved: the line keeps
    the order the videos were asked for, and passing one over has exactly the
    effect of sending it to the bottom, since everything that can start goes
    first. A line holding nothing but videos yields ``None`` — the queue waits,
    the GPU stays out of the show's way, and the next image asked for is what
    starts it moving again.
    """
    for job in line:
        if not (videos_held and is_video(job)):
            return job
    return None


def held_back(line: list, *, videos_held: bool) -> list:
    """The jobs in ``line`` that cannot start while the gate is what it is.

    What a surface asks to explain a queue that isn't moving: with videos held,
    every video in the line is waiting on the show rather than on the GPU.
    """
    return [job for job in line if videos_held and is_video(job)]
