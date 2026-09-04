from reviewer.config import AppConfig
from reviewer.reviewers import ClaudeCliCodeReviewer, AnthropicCodeReviewer, GeminiCodeReviewer, OpenAiCodeCodeReviewer, \
    CodexCliCodeReviewer, AgyCliCodeReviewer, DeepSeekCodeReviewer, CodeReviewer, GroqCodeReviewer


def create_reviewer(config: AppConfig) -> CodeReviewer:

    match config.provider:

        case "claude-cli":
            return ClaudeCliCodeReviewer(
                config
            )

        case "anthropic":
            return AnthropicCodeReviewer(
                config
            )
        case "gemini":
            return GeminiCodeReviewer(
                config
            )
        case "openai":
            return OpenAiCodeCodeReviewer(
                config
            )
        case "deepseek":
            return DeepSeekCodeReviewer(
                config
            )
        case "codex":
            return CodexCliCodeReviewer(
                config
            )
        case "agy":
            return AgyCliCodeReviewer(
                config
            )
        case "groq":
            return GroqCodeReviewer(
                config
            )
        case _:
            raise ValueError(
                f"Unsupported provider: {config.provider}"
            )
