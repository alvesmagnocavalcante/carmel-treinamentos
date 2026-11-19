from django.core.exceptions import ValidationError

MIN_LENGTH = 11
MAX_LENGTH = 128  # só para não aceitar textos gigantes; não limita senhas de verdade

POLICY_TEXT = f"Mínimo de {MIN_LENGTH} caracteres, com letras, números e caracteres especiais (como ! @ # $ %)."


class PasswordPolicyValidator:
    """Senha forte: pelo menos 11 caracteres, com letra, número e caractere especial."""

    def validate(self, password, user=None):
        problems = []
        if len(password) < MIN_LENGTH:
            problems.append(f"ter pelo menos {MIN_LENGTH} caracteres")
        if len(password) > MAX_LENGTH:
            raise ValidationError(f"A senha pode ter no máximo {MAX_LENGTH} caracteres.", code="password_too_long")
        if not any(c.isalpha() for c in password):
            problems.append("ter letras")
        if not any(c.isdigit() for c in password):
            problems.append("ter números")
        if not any(not c.isalnum() and not c.isspace() for c in password):
            problems.append("ter caracteres especiais (como ! @ # $ %)")
        if problems:
            raise ValidationError("A senha precisa " + ", ".join(problems[:-1]) + (" e " if len(problems) > 1 else "")
                                  + problems[-1] + ".", code="password_too_weak")

    def get_help_text(self):
        return POLICY_TEXT
