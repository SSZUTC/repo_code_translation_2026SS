from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.tools import tool
from langchain_core.prompts import PromptTemplate
from langchain.memory import ConversationBufferMemory
from langgraph.prebuilt import ToolNode

# ==========================
# 1. 工具 (TOOL) → 你已经有了，稍微强化描述
# ==========================
@tool
def get_weather(city: str) -> str:
    """
    查询指定城市的天气
    这个工具会返回该城市的天气情况
    Args:
        city: 城市名称
    """
    return f"{city} 的天气是：惊天雷阵雨"

# ==========================
# 2. 规划 (PLANNING) → 自定义Prompt，让Agent会思考
# ==========================
prompt = PromptTemplate.from_template("""
You are a helpful assistant.
Answer the user's question politely.

You have access to the following tool:
{tools}

Conversation history:
{chat_history}

Follow the ReAct format:
Thought: I need to...
Action: the tool name, which must be one of [{tool_names}].
Action Input: the parameters
Observation: tool result
Final Answer: ...

Question: {input}
Thought:{agent_scratchpad}
""")

# ==========================
# 3. 记忆 (MEMORY) → 多轮对话记住上下文
# ==========================
memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True
)

# ==========================
# 4. LLM 模型
# ==========================
llm = ChatOpenAI(
    model="openai/gpt-4o",
    api_key="",
    base_url="https://openrouter.ai/api/v1",
    temperature=0
)

# ==========================
# 5. 创建 ReAct Agent
# ==========================
tools = [get_weather]
agent = create_react_agent(
    llm,
    tools,
    prompt=prompt
)

# ==========================
# 6. 执行器 (AgentExecutor)
# ==========================
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    memory=memory,
    verbose=True,
    handle_parsing_errors=True
)

# ==========================
# 测试：多轮对话 + 记忆 + 规划 + 工具
# ==========================
if __name__ == "__main__":
    print("第一轮对话：")
    res1 = agent_executor.invoke({"input": "北京天气如何？"})
    print("AI:", res1["output"])

    print("\n第二轮对话（测试记忆是否生效）：")
    res2 = agent_executor.invoke({"input": "那上海呢？"})
    print("AI:", res2["output"])