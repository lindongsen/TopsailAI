# Add TopsailAI command directories for login and interactive shells.
case ":${PATH}:" in
    *:/TopsailAI/src/topsailai/bin:*) ;;
    *) PATH="/TopsailAI/src/topsailai/bin:${PATH}" ;;
esac
case ":${PATH}:" in
    *:/TopsailAI/src/topsailai_data/bin:*) ;;
    *) PATH="/TopsailAI/src/topsailai_data/bin:${PATH}" ;;
esac
export PATH
