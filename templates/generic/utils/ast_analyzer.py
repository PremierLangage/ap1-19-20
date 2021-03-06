from ast import *


class AstAnalyzer:
    class _CallVisitor(NodeVisitor):
        def __init__(self):
            self.calls = []

        def visit_Call(self, node):
            if isinstance(node.func, Name):
                self.calls.append(node.func.id)
            self.generic_visit(node)

    def __init__(self, source: str):
        self.source = source
        self.ast = parse(source)

    def function_exists(self, funcname: str):
        return any(isinstance(node, FunctionDef)
                   and node.name == funcname
                   for node in iter_child_nodes(self.ast))

    _for_classes = (For, ListComp, SetComp, DictComp, GeneratorExp)

    def has_loop(self, scope=None):
        def find_loop(node):
            if isinstance(node, While):
                return 'while', node.lineno
            if any(isinstance(node, nodetype) for nodetype in
                   self._for_classes):
                return 'for', node.lineno
            for node in iter_child_nodes(node):
                res = find_loop(node)
                if res is not None:
                    return res
            return None

        tree = self.clip(scope)
        return find_loop(tree)

    def calls_list(self, scope=None):
        visitor = self._CallVisitor()
        tree = self.clip(scope)
        visitor.visit(tree)
        return visitor.calls

    def clip(self, scope):
        def find_scope(node):
            if isinstance(node, FunctionDef) or isinstance(node, ClassDef):
                if node.name == scope:
                    return node
            for node in iter_child_nodes(node):
                res = find_scope(node)
                if res is not None:
                    return res
            return None

        if scope is None:
            return self.ast
        return find_scope(self.ast)

    def is_simple_recursive(self, funcname: str):
        return funcname in self.calls_list(funcname)

    def may_call_itself(self, funcname):
        to_visit = {funcname}
        visited = set()

        while to_visit:
            f = to_visit.pop()
            calls = self.calls_list(f)
            if funcname in calls:
                return True
            visited.add(f)
            to_visit.update(set(calls) - visited)

        return False


if __name__ == "__main__":
    from textwrap import dedent

    code_for = dedent("""
    for i in range(5):
        print(i)
    """)

    code_while = dedent("""
    i = 0
    while i < 5:
        print(i)
        i += 1
    """)

    code_comprehension = dedent("""
    [i for i in range(5)]
    """)

    code_without_loop = 'print("Hello world!")'

    code_rec = dedent("""
    def f(n):
        if n <= 1:
            return 1
        else:
            return n * f(f(n-1))

    def g(n):
        if n <= 1:
            return 1
        else:
            return n * f(n-1)
    """)

    code_even_odd = dedent("""
    def even(n):
        if n == 0:
            return True
        else:
            return odd(n - 1)

    def odd(n):
        if n == 0:
            return False
        else:
            return even(n-1)
    """)

    a = AstAnalyzer(code_for)
    print(a.has_loop())

    a = AstAnalyzer(code_while)
    print(a.has_loop())

    a = AstAnalyzer(code_comprehension)
    print(a.has_loop())

    a = AstAnalyzer(code_without_loop)
    print(a.has_loop())

    a = AstAnalyzer(code_rec)
    print(a.calls_list())
    print(a.calls_list("f"))
    print(a.calls_list("g"))
    print(a.is_simple_recursive("f"))
    print(a.is_simple_recursive("g"))

    a = AstAnalyzer(code_even_odd)
    print(a.calls_list())
    print(a.calls_list("even"))
    print(a.calls_list("odd"))
    print(a.is_simple_recursive("even"))
    print(a.is_simple_recursive("odd"))
    print(a.may_call_itself("even"))
    print(a.may_call_itself("odd"))
