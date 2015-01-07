import sublime

class ThreadProgress():
    def __init__(self, thread, message):
        self.th = thread
        self.msg = message
        self.add = 1
        self.size = 8
        self.speed = 100
        sublime.set_timeout(lambda: self.run(0), self.speed)

    def run(self, i):
        if not self.th.is_alive():
            sublime.status_message('')
            return

        before = i % self.size
        after = (self.size - 1) - before

        sublime.status_message('%s [%s=%s]' % (self.msg, ' ' * before, ' ' * after))

        if not after:
            self.add = -1
        if not before:
            self.add = 1

        i += self.add

        sublime.set_timeout(lambda: self.run(i), self.speed)
