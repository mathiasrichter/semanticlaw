from rdflib import Graph
from pyshacl import validate
import os
import re
from erdi8 import Erdi8
import cmd2

ERDI = Erdi8()


class State:
    ROMAN_ORD = "roman"
    INT_ORD = "int"

    BG = "Bundesgesetz"
    BV = "Bundesverordnung"
    KG = "Kantonsgesetz"
    KVO = "Kantonsverordnung"
    KV = "Kantonsverfügung"
    ABSCH = "Abschnitt"
    ART = "Artikel"
    PAR = "Paragraph"
    ABS = "Absatz"
    LIT = "Litera"

    CLASSES = [BG, BV, KG, KVO, KV, ABSCH, ART, PAR, ABS, LIT]

    def __init__(self, tmp_file_name: str = "tmp.ttl"):
        self.graph = Graph()
        self.tmp_file_name = tmp_file_name
        self.namespace = "http://example.org/"
        self.init()
        self.saved_prev = None
        self.last_id = None


    def init(self):
        self.cur_class = None
        self.cur_id = None
        self.cur_parent = None
        self.cur_prev = None
        self.cur_next = None
        self.cur_ord = None
        self.cur_title = None
        self.cur_content = None
        self.dirty = False
        self.saved = True

    def namespace(self, namespace: str):
        self.namespace = namespace

    def load(self, file_name: str):
        self.graph = Graph().parse(file_name, format='ttl')

    def show(self):
        return self.graph.serialize(format='ttl')

    def save(self, file_name: str):
        with open(file_name, "w") as f:
            f.writelines(self.graph.serialize(format='ttl'))
        self.saved = True

    def commit(self) -> str:
        if self.dirty is True:
            prefix  = "PREFIX : <" + self.namespace + "> "
            prefix += "PREFIX sl:<https://raw.githubusercontent.com/mathiasrichter/semanticlaw/main/swisslaw.ttl#> "
            query = prefix + "DELETE { :" + self.cur_id + " ?p ?o . } "
            query += "WHERE { :" + self.cur_id + " ?p ?o . } "
            print(query)
            self.graph.update(query)
            query = prefix + "INSERT DATA { "
            query += ":" + self.cur_id + " a sl:" + self.cur_class + " . "
            if self.cur_parent is not None:
                query += ":" + self.cur_id + " sl:parent :" + self.cur_parent + " . "
            if self.cur_prev is not None:
                query += ":" + self.cur_id + " sl:prev :" + self.cur_prev + " . "
            if self.cur_next is not None:
                query += ":" + self.cur_next + " sl:next :" + self.cur_next + " . "
            if self.cur_title is not None:
                query += ":" + self.cur_id + ' sl:title """' + self.cur_prev + '""" . '
            if self.cur_content is not None:
                query += ":" + self.cur_id + ' sl:content """' + self.cur_content + '""" . '
            if self.cur_ord is not None:
                if type(self.cur_ord) == int:
                    query += ":" + self.cur_id + " sl:ord " + str(self.cur_ord) + " . "
                else:
                    query += ":" + self.cur_id + ' sl:ord "' + self.cur_ord + '" . '
            query += "}"
            print(query)
            self.graph.update(query)
            self.dirty = False

    def up(self):
        self.saved_prev = self.cur_id
        if self.cur_parent is not None:
            self.set(self.cur_parent)

    def down(self):
        if self.saved_prev is not None:
            self.cur_next = ERDI.increment(self.saved_prev)
        else:
            self.cur_next = ERDI.increment(self.cur_id)
        self.commit()
        self.dirty = True
        self.saved = False
        self.cur_parent = self.cur_id
        self.cur_id = self.cur_next
        self.cur_prev = self.cur_parent
        self.cur_next = None
        self.cur_title = None
        self.cur_content = None
        if self.cur_class in [self.BG, self.BV, self.KG, self.KVO, self.KV]:
            self.cur_class = self.ABSCH
            self.cur_ord = 1
        elif self.cur_class == self.ABSCH:
            self.cur_class = self.ART
            self.cur_ord = 1
        elif self.cur_class == self.ART:
            self.cur_class = self.ABS
            self.cur_ord = 1
        elif self.cur_class == self.PAR:
            self.cur_class = self.ABS
            self.cur_ord = 1
        elif self.cur_class == self.ABS:
            self.cur_class = self.LIT
            self.cur_ord = "a"
        elif self.cur_class == self.LIT:
            pass  # no further hierarchy level below lit

    def next(self):
        if self.saved_prev is not None:
            self.cur_next = ERDI.increment(self.saved_prev)
        else:
            self.cur_next = ERDI.increment(self.cur_id)
        self.commit()
        self.dirty = True
        self.saved = False
        if self.saved_prev is not None:
            self.cur_prev = self.saved_prev
            self.saved_prev = None
        else:
            self.cur_prev = self.cur_id
        self.cur_id = self.cur_next
        self.cur_next = None
        if self.cur_ord is not None:
            if type(self.cur_ord) == int:
                self.cur_ord += 1
            else:
                self.cur_ord = chr((ord(self.cur_ord) + 1 - 65) % 26 + 91)
        self.cur_title = None
        self.cur_content = None

    def prev(self):
        if self.cur_prev is not None:
            self.set(self.cur_prev)

    def set_title(self, title: str):
        self.cur_title = title
        self.dirty = True

    def set_content(self, content: str):
        self.cur_content = content
        self.dirty = True

    def extract_id(self, value: str) -> str:
        slashpos = value.rfind("/")
        hashpos = value.rfind("#")
        if slashpos > hashpos:
            return value[slashpos + 1 : len(value)]
        if hashpos > slashpos:
            return value[hashpos + 1 : len(value)]
        return None

    def set(self, id: str):
        query = (
            """
                SELECT DISTINCT ?element ?predicate ?object
                WHERE
                {
                    ?element ?predicate ?object .
                    FILTER(STRENDS(STR(?element), '"""
            + id
            + """')) .
                }
        """
        )
        result = self.graph.query(query)
        self.init()
        self.cur_id = id
        for r in result:
            if str(r.predicate).endswith("type"):
                self.cur_class = self.extract_id(str(r.object))
            if str(r.predicate).endswith("prev"):
                self.cur_prev = self.extract_id(str(r.object))
            if str(r.predicate).endswith("next"):
                self.cur_next = self.extract_id(str(r.object))
            if str(r.predicate).endswith("parent"):
                self.cur_parent = self.extract_id(str(r.object))
            if str(r.predicate).endswith("title"):
                self.cur_title = str(r.object)
            if str(r.predicate).endswith("content"):
                self.cur_content = str(r.object)
            if str(r.predicate).endswith("ord"):
                s = str(r.object)
                if s.isdigit() == True:
                    self.cur_ord = int(s)
                else:
                    self.cur_ord = s

    def start(self, clazz: str):
        self.init()
        self.cur_class = clazz
        self.cur_id = ERDI.increment(clazz.lower().replace("l", ""))
        self.dirty = True

    def to_string(self):
        s = """
------------------------------------------
Type:      {}
Id:        {}
Parent:    {}
Prev:      {}
Next:      {}
Title:     {}
Content:   {}
Ord:       {}
------------------------------------------
        """
        return s.format(
            (self.cur_class) if self.cur_class is not None else "",
            (":" + self.cur_id) if self.cur_id is not None else "",
            (":" + self.cur_parent) if self.cur_parent is not None else "",
            (":" + self.cur_prev) if self.cur_prev is not None else "",
            (":" + self.cur_next) if self.cur_next is not None else "",
            (self.cur_title[0:10] + "...") if self.cur_title is not None else "",
            (self.cur_content[0:20] + "...") if self.cur_content is not None else "",
            self.cur_ord if self.cur_ord is not None else "",
        )


class Collector(cmd2.Cmd):
    state = State()

    def __init__(
        self,
    ):
        super().__init__(multiline_commands=["title", "content"])

    def do_start(self, line: str):
        if line in self.state.CLASSES:
            self.state.start(line)
        print(self.state.to_string())

    def do_status(self, line: str):
        print(self.state.to_string())

    def do_title(self, line: str):
        self.state.set_title(line)
        print(self.state.to_string())

    def do_content(self, line: str):
        self.state.set_content(line)
        print(self.state.to_string())

    def do_load(self, line: str):
        self.state.load(line)

    def do_next(self, line: str):
        if self.state.dirty == True:
            print(
                "You have uncommitted changes. Please commit or use set previous togo back to the last element."
            )
            return
        self.state.next()
        print(self.state.to_string())

    def do_down(self, line: str):
        if self.state.dirty == True:
            print(
                "You have uncommitted changes. Please commit or use set previous togo back to the last element."
            )
            return
        self.state.down()
        print(self.state.to_string())

    def do_ord(self, line:str):
        if line.isdigit():
            self.state.cur_ord = int(line)
        else:
            self.state.cur_ord = line
        print(self.state.to_string())
            
    def do_type(self, line:str):
       self.state.cur_class = line
       print(self.state.to_string())
            
    def do_prev(self, line: str):
        if self.state.dirty == True:
            print(
                "You have uncommitted changes. Please commit or use set previous togo back to the last element."
            )
            return
        self.state.prev()
        print(self.state.to_string())

    def do_up(self, line: str):
        if self.state.dirty == True:
            print(
                "You have uncommitted changes. Please commit or use set previous togo back to the last element."
            )
            return
        self.state.up()
        print(self.state.to_string())

    def do_save(self, line: str):
        self.state.save(line)

    def do_commit(self, line: str):
        self.state.commit()

    def do_show(self, line: str):
        print(self.state.show())

    def do_switch(self, line: str):
        self.state.set(line)
        print(self.state.to_string())

    def do_exit(self, line: str):
        if line == "!":
            exit()
        if self.state.dirty == True:
            print(
                "You have uncommitted changes. Either commit or use 'exit !' to exit without committing."
            )
            return
        if self.state.saved == False:
            print(
                "You have unsaved changes. Either save or use 'exit !' to exit without committing."
            )
            return
        exit()


if __name__ == "__main__":
    app = Collector()
    app.use_rawinput = True
    app.cmdloop()
