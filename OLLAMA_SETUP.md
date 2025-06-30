# HomePay AI Support Agent - Ollama LLM Integration

## Overview
This document describes the Ollama LLM integration for the HomePay AI Support Agent, providing enhanced Hebrew language processing capabilities.

## Installation Summary
- **Date**: June 30, 2025
- **Server**: AWS EC2 (100.26.100.95)
- **Ollama Version**: 0.9.3
- **Model**: llama2:7b (3.8GB)
- **Configuration**: CPU-only mode

## System Architecture
The HomePay AI Support Agent uses a hybrid LLM approach:

1. **Primary**: Local Ollama LLM (llama2:7b)
2. **Secondary**: Anthropic Claude API (if configured)
3. **Fallback**: Enhanced keyword matching with relevance scoring

## Configuration Details

### Environment Variables
```bash
OLLAMA_URL=http://localhost:11434
LLM_MODEL=llama2:7b
USE_HYBRID_LLM=true
```

### Service Status
- **Ollama Service**: Active and enabled
- **Port**: 11434 (localhost only)
- **Memory Usage**: ~11.7GB
- **CPU Threads**: 8

## Performance Considerations
- **Response Time**: 15+ seconds for complex queries
- **Resource Usage**: High memory consumption (11.7GB)
- **Fallback Behavior**: System gracefully falls back to keyword matching when Ollama is slow

## Benefits
- Enhanced Hebrew language understanding
- More contextual and nuanced responses
- Better handling of complex multi-part questions
- Improved conversation flow and context retention

## Maintenance
- Monitor memory usage and CPU load
- Check Ollama service status: `systemctl status ollama`
- View logs: `journalctl -u ollama -f`
- Restart if needed: `sudo systemctl restart ollama`

## Troubleshooting
- If responses are slow, the system automatically falls back to keyword matching
- Check Ollama API availability: `curl http://localhost:11434/api/tags`
- Verify model installation: `ollama list`

## Future Improvements
- Consider upgrading to a more efficient model for better performance
- Implement response caching for frequently asked questions
- Monitor and optimize resource usage
