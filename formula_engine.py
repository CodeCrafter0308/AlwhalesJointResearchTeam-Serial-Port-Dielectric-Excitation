import ast
import math
from numbers import Real


class FormulaError(ValueError):
    pass


class FormulaEvaluator:
    FUNCTIONS = {
        "abs": abs,
        "min": min,
        "max": max,
        "pow": pow,
        "round": round,
        "sqrt": math.sqrt,
        "log": math.log,
        "log10": math.log10,
        "exp": math.exp,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "asin": math.asin,
        "acos": math.acos,
        "atan": math.atan,
        "floor": math.floor,
        "ceil": math.ceil,
    }
    CONSTANTS = {
        "pi": math.pi,
        "e": math.e,
    }
    ALLOWED_NODES = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Call,
        ast.Name,
        ast.Load,
        ast.Constant,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Pow,
        ast.Mod,
        ast.USub,
        ast.UAdd,
    )

    def validate(self, expression, variable_names):
        expression = expression.strip()
        if not expression:
            return

        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise FormulaError(f"公式语法错误：{exc.msg}") from exc

        allowed_names = set(variable_names) | set(self.FUNCTIONS) | set(self.CONSTANTS)
        for node in ast.walk(tree):
            if not isinstance(node, self.ALLOWED_NODES):
                raise FormulaError(f"公式中不允许使用 {type(node).__name__}")
            if isinstance(node, ast.Name) and node.id not in allowed_names:
                raise FormulaError(f"未知变量或函数：{node.id}")
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name) or node.func.id not in self.FUNCTIONS:
                    raise FormulaError("公式只能调用允许的数学函数")
                if node.keywords:
                    raise FormulaError("公式函数不支持关键字参数")

    def evaluate(self, expression, variables):
        expression = expression.strip()
        if not expression:
            return variables.get("y")

        self.validate(expression, variables.keys())
        namespace = {}
        namespace.update(self.FUNCTIONS)
        namespace.update(self.CONSTANTS)
        namespace.update(variables)

        try:
            value = eval(compile(expression, "<channel-formula>", "eval"), {"__builtins__": {}}, namespace)
        except Exception as exc:
            raise FormulaError(str(exc)) from exc

        if not isinstance(value, Real) or isinstance(value, bool):
            raise FormulaError("公式结果必须是数值")
        return float(value)

