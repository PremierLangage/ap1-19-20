import sys
from copy import deepcopy
from io import StringIO
from typing import NoReturn, List, Callable
from unittest import mock

import testfeedback as fb
from grader import GraderError
from mockinput import mock_input


def new_variables(previous, current) -> dict:
    return {var: current[var] for var in current.keys() - previous.keys()}


def deleted_variables(previous, current) -> List[str]:
    return list(previous.keys() - current.keys())


def modified_variables(previous, current, cmp=lambda x, y: x == y) -> dict:
    return {var: current[var] for var in previous.keys() & current.keys()
            if not cmp(previous[var], current[var])}


def unchanged_variables(previous, current, cmp=lambda x, y: x == y) -> dict:
    return {var: previous[var] for var in previous.keys() & current.keys()
            if cmp(previous[var], current[var])}


class CodeRunner:
    """Code runner for Python exercises.

    Instances store a piece of student code.
    Provides methods for code execution, simulating standard input and output
    if necessary and keeping track of global state changes.
    """

    def __init__(self, code: str):
        """Build CodeRunner object.

        :param code: student code to evaluate.
        """
        self.code = code

        # execution context (backup)
        self.previous_state = {}
        self.previous_inputs = []

        # execution context (current)
        self.current_state = {}
        self.current_inputs = []
        self.argv = []

        # execution effects
        self.output = ""
        self.exception = None
        self.result = None

        # test description
        self.title = None
        self.descr = None
        self.hint = None

        # history and feedback
        self.tests = []  # List[Union[fb.TestGroup, fb.TestFeedback]]
        self.current_test_group = None
        self.current_test = None

    def copy(self):
        r = CodeRunner(self.code)
        r.previous_state = deepcopy(self.previous_state)
        r.current_state = deepcopy(self.current_state)
        r.previous_inputs = self.previous_inputs.copy()
        r.current_inputs = self.current_inputs.copy()
        r.argv = self.argv.copy()
        r.output = self.output
        r.exception = self.exception
        r.result = deepcopy(self.result)
        return r

    """Setters for execution context."""

    def set_title(self, title):
        self.title = title

    def exec_preamble(self, preamble: str, **kwargs) -> NoReturn:
        exec(preamble, self.current_state, **kwargs)
        del self.current_state['__builtins__']

    def set_globals(self, **variables) -> NoReturn:
        self.previous_state = None
        self.current_state = variables

    def set_state(self, state: dict) -> NoReturn:
        self.previous_state = None
        self.current_state = state

    def set_argv(self, argv: List[str]) -> NoReturn:
        self.argv = argv.copy()

    def set_inputs(self, inputs: List[str]) -> NoReturn:
        self.current_inputs = inputs.copy()

    """Feedback management."""

    def begin_test_group(self, title: str) -> NoReturn:
        self.current_test_group = fb.TestGroupFeedback(title)
        self.tests.append(self.current_test_group)

    def end_test_group(self) -> NoReturn:
        self.current_test_group = None

    def record_test(self, test: fb.TestFeedback) -> NoReturn:
        self.current_test = test
        if self.current_test_group:
            self.current_test_group.append(test)
        else:
            self.tests.append(test)

    def record_assertion(self, assertion: fb.AssertFeedback) -> NoReturn:
        if self.current_test:
            self.current_test.append(assertion)
            if not assertion.status:
                self.current_test.status = False
                if self.current_test_group:
                    self.current_test_group.status = False
        else:
            raise GraderError("Aucune exécution préalable, assertion "
                              "impossible.")

    def render_tests(self):
        return "\n".join(test.render() for test in self.tests)

    """Code execution."""

    def summarize_changes(self):
        # TODO: cache results if clean
        deleted = deleted_variables(self.previous_state, self.current_state)
        modified = modified_variables(self.previous_state, self.current_state)
        added = new_variables(self.previous_state, self.current_state)

        n = len(self.previous_inputs) - len(self.current_inputs)
        inputs = self.previous_inputs[:n]

        return added, deleted, modified, inputs

    def run(self, expression: str = None, **kwargs) -> NoReturn:
        """
        Run the student code.
        """
        # set title
        if 'title' in kwargs:
            self.title = kwargs['title']

        # set description
        if 'descr' in kwargs:
            self.descr = kwargs['descr']

        # set hint
        if 'hint' in kwargs:
            self.hint = kwargs['hint']

        # set global variables (overwrites the whole global namespace)
        if 'globals' in kwargs:
            self.set_state(kwargs['globals'])

        # set available inputs
        if 'inputs' in kwargs:
            self.set_inputs(kwargs['inputs'])

        # set available program parameters (overrides sys.argv)
        if 'argv' in kwargs:
            self.set_argv(kwargs['argv'])

        # backup starting state
        self.previous_state = deepcopy(self.current_state)
        self.previous_inputs = self.current_inputs.copy()

        # reset outputs
        self.result = None
        self.exception = None

        # prepare StringIO for stdout simulation
        out_stream = StringIO()

        # run the code while mocking input, sys.argv and stdout printing
        with mock_input(self.current_inputs, self.current_state):
            with mock.patch.object(sys, 'argv', self.argv):
                with mock.patch.object(sys, 'stdout', out_stream):
                    try:
                        if expression is None:
                            exec(self.code, self.current_state)
                        else:
                            self.result = eval(expression, self.current_state)
                    except Exception as e:
                        self.exception = e

        # cleanup final state for feedback
        del self.current_state['__builtins__']
        # store generated output
        self.output = out_stream.getvalue()
        # generate execution report
        self.record_test(fb.TestFeedback(self.copy(), expression, **kwargs))

        # manage exceptions
        if 'exception' in kwargs:
            # if parameter exception=SomeExceptionClass is passed, silently
            # check it is indeed raised
            self.assert_exception(kwargs['exception'])
        elif 'allow_exception' not in kwargs or not kwargs['allow_exception']:
            # unless exceptions are explicitly allowed by parameter
            # allow_exception=True, forbid them
            self.assert_no_exception(report_success=False)

        # check global values
        if 'values' in kwargs:
            # for now we have no facility to check that some variable was
            # deleted, we only check that some variables exist
            self.assert_variable_values(kwargs['values'])
        if ('allow_global_change' in kwargs
                and not kwargs['allow_global_change']):
            # forbid changes to global variables
            self.assert_no_global_change()

        # check for standard output
        if 'output' in kwargs:
            self.assert_output(kwargs['output'])

        # check for evaluation result, only valid if an expression is provided
        if 'result' in kwargs:
            if 'expression' is None:
                raise GraderError("Vérification du résultat demandée mais pas "
                                  "d'expression fournie")
            else:
                self.assert_result(kwargs['result'])

    """Assertions."""

    def assert_output(self, expected,
                      cmp: Callable = lambda x, y: x == y):
        status = cmp(expected, self.output)
        self.record_assertion(fb.OutputAssertFeedback(status, expected))

    def assert_result(self, expected,
                      cmp: Callable = lambda x, y: x == y):
        status = cmp(expected, self.result)
        self.record_assertion(fb.ResultAssertFeedback(status, expected))

    def assert_variable_values(self, cmp=lambda x, y: x == y, **expected):
        if not expected:
            return
        missing = deleted_variables(expected, self.current_state)
        incorrect = modified_variables(expected, self.current_state, cmp)

        status = not (missing or incorrect)
        self.record_assertion(fb.VariableValuesAssertFeedback(
            status, expected, missing, incorrect))

    def assert_no_global_change(self):
        added, deleted, modified, _ = self.summarize_changes()
        status = not(added or deleted or modified)
        self.record_assertion(fb.NoGlobalChangeAssertFeedback(status))

    def assert_no_exception(self, **params):
        status = self.exception is None
        self.record_assertion(fb.NoExceptionAssertFeedback(status, **params))

    def assert_exception(self, exception_type):
        status = isinstance(self.exception, exception_type)
        self.record_assertion(
            fb.ExceptionAssertFeedback(status, exception_type))

